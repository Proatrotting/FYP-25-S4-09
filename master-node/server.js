const express = require('express');
const { Pool } = require('pg');
const { v4: uuidv4 } = require('uuid');
const fs = require('fs').promises;
const path = require('path');
const axios = require('axios');
const app = express();

// Configure Express to handle large payloads (up to 200MB)
app.use(express.json({ limit: '200mb', parameterLimit: 1000000 }));
app.use(express.urlencoded({ limit: '200mb', extended: true, parameterLimit: 1000000 }));

// Add request logging middleware
app.use((req, res, next) => {
    console.log(`[${new Date().toISOString()}] ${req.method} ${req.path}`);
    if (req.path === '/files' && req.method === 'POST') {
        console.log('=== FILE CREATION REQUEST ===');
        console.log('Headers:', JSON.stringify(req.headers, null, 2));
        console.log('Body keys:', Object.keys(req.body || {}));
    }
    next();
});

// Increase timeout for large uploads
app.use((req, res, next) => {
    req.setTimeout(600000); // 10 minutes
    res.setTimeout(600000); // 10 minutes
    next();
});

// PostgreSQL connection pool
// PostgreSQL connection pool
let pool;

// Initialize PostgreSQL database connection with enhanced configuration
async function initializeDatabase() {
    try {
        // Don't use connectionString - use direct config object instead!
        const poolConfig = {
            host: process.env.POSTGRES_HOST || 'postgres_db',
            port: parseInt(process.env.POSTGRES_PORT || '5432'),
            user: process.env.POSTGRES_USER || 'user',
            password: process.env.POSTGRES_PASSWORD || 'password',
            database: process.env.POSTGRES_DB || 'database',
            ssl: process.env.POSTGRES_SSL === 'true' ? { rejectUnauthorized: false } : false,
            max: parseInt(process.env.POSTGRES_MAX_CONNECTIONS || '25'),
            min: parseInt(process.env.POSTGRES_MIN_CONNECTIONS || '5'),
            idleTimeoutMillis: 30000,
            connectionTimeoutMillis: 5000,
            acquireTimeoutMillis: 60000,
            createTimeoutMillis: 30000,
            destroyTimeoutMillis: 5000,
            reapIntervalMillis: 1000,
            createRetryIntervalMillis: 100,
            propagateCreateError: false,
        };
        
        pool = new Pool(poolConfig);
        
        console.log('Master Node: Initializing PostgreSQL connection...');
        console.log('Host:', poolConfig.host);
        console.log('Port:', poolConfig.port);
        console.log('Database:', poolConfig.database);
        console.log('User:', poolConfig.user);
        
        // Test connection with retry logic
        let retries = 5;
        while (retries > 0) {
            try {
                const testResult = await pool.query('SELECT NOW() as current_time, version() as pg_version');
                console.log('PostgreSQL connection successful!');
                console.log('Current time:', testResult.rows[0].current_time);
                console.log('PostgreSQL version:', testResult.rows[0].pg_version.split(' ')[0]);
                break;
            } catch (err) {
                retries--;
                if (retries === 0) {
                    throw err;
                }
                console.log(`Connection failed, retrying... (${retries} attempts left)`);
                await new Promise(resolve => setTimeout(resolve, 2000));
            }
        }
        
        // Set up connection monitoring
        pool.on('connect', () => {
            console.log('New PostgreSQL client connected');
        });
        
        pool.on('error', (err) => {
            console.error('PostgreSQL pool error:', err);
        });
        
        return pool;
        
    } catch (error) {
        console.error('Error initializing PostgreSQL connection:', error);
        process.exit(1);
    }
}

// Enhanced helper function to execute queries with better error handling and logging
async function query(text, params = [], options = {}) {
    const start = Date.now();
    const client = options.client || null; // Allow using specific client for transactions
    
    try {
        let result;
        
        if (client) {
            // Use provided client (for transactions)
            result = await client.query(text, params);
        } else {
            // Use pool for regular queries
            result = await pool.query(text, params);
        }
        
        const duration = Date.now() - start;
        
        // Log query execution (only log first 100 chars of SQL for security)
        const sqlPreview = text.length > 100 ? text.substring(0, 100) + '...' : text;
        console.log(`SQL executed successfully: ${sqlPreview} | Duration: ${duration}ms | Rows: ${result.rowCount || 0}`);
        
        return result;
        
    } catch (error) {
        const duration = Date.now() - start;
        console.error(`SQL execution error after ${duration}ms:`, {
            sql: text.substring(0, 100),
            params: params,
            error: error.message,
            code: error.code,
            detail: error.detail
        });
        throw error;
    }
}

// Transaction helper function
async function withTransaction(callback) {
    const client = await pool.connect();
    try {
        await client.query('BEGIN');
        console.log('Transaction started');
        
        const result = await callback(client);
        
        await client.query('COMMIT');
        console.log('Transaction committed');
        
        return result;
    } catch (error) {
        await client.query('ROLLBACK');
        console.log('Transaction rolled back due to error:', error.message);
        throw error;
    } finally {
        client.release();
    }
}

// Database health check function
async function checkDatabaseHealth() {
    try {
        const result = await query('SELECT COUNT(*) as table_count FROM information_schema.tables WHERE table_schema = $1', ['public']);
        const tableCount = parseInt(result.rows[0].table_count);
        
        if (tableCount === 0) {
            console.warn('Warning: No tables found in public schema. Database may not be initialized.');
            return { healthy: false, reason: 'No tables found' };
        }
        
        // Check if critical tables exist
        const criticalTables = ['account', 'node', 'file_objects'];
        for (const table of criticalTables) {
            const tableExists = await query(
                'SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = $1 AND table_name = $2)',
                ['public', table]
            );
            
            if (!tableExists.rows[0].exists) {
                console.warn(`Critical table '${table}' not found`);
                return { healthy: false, reason: `Missing table: ${table}` };
            }
        }
        
        return { healthy: true, tables: tableCount };
    } catch (error) {
        console.error('Database health check failed:', error);
        return { healthy: false, reason: error.message };
    }
}

const NODE_ID = uuidv4();
const NODE_PORT = process.env.NODE_PORT || 3000;
const NODE_ROLE = 'MASTER';
const NODE_HOSTNAME = process.env.NODE_HOSTNAME || 'master-node';
const STORAGE_PATH = process.env.STORAGE_PATH || '/data/storage';
const HEARTBEAT_INTERVAL = parseInt(process.env.HEARTBEAT_INTERVAL) || 10000;

// Note: Database schema initialization should be done via Database.sql migration
// This file assumes the schema already exists in PostgreSQL

async function ensureStorageDirectory() {
    try {
        await fs.access(STORAGE_PATH);
    } catch {
        await fs.mkdir(STORAGE_PATH, { recursive: true });
    }
}

async function initialiseDB() {
    try {
        await ensureStorageDirectory();
        
        const apiEndpoint = `http://${NODE_HOSTNAME}:${NODE_PORT}`;
        
        // Insert or update master node record
        await query(`
            INSERT INTO node (node_id, api_endpoint, node_role, hostname, is_active, uptimed_at, heartbeat_at)
            VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
            ON CONFLICT (node_id) DO UPDATE SET
                api_endpoint = EXCLUDED.api_endpoint,
                is_active = EXCLUDED.is_active,
                heartbeat_at = NOW()
        `, [NODE_ID, apiEndpoint, NODE_ROLE, NODE_HOSTNAME, true]);
        
        const totalBytes = 12 * 1024 * 1024 * 1024; // 12 GB
        
        // Insert or update capacity
        await query(`
            INSERT INTO node_capacity (node_id, total_bytes, used_bytes, available_bytes, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (node_id) DO UPDATE SET
                total_bytes = EXCLUDED.total_bytes,
                updated_at = NOW()
        `, [NODE_ID, totalBytes, 0, totalBytes]);
        
        console.log(`Master Node ${NODE_ID} initialized in database.`);
        console.log('Hostname:', NODE_HOSTNAME);
        console.log('Role:', NODE_ROLE);
        console.log('Storage Path:', STORAGE_PATH);
    } catch (error) {
        console.error('Error initializing master node in database:', error);
        process.exit(1);
    }
}

async function heartbeat() {
    try {
        const initTime = Date.now();
        const latency = Date.now() - initTime;
        
        await query(`
            UPDATE node 
            SET heartbeat_at = NOW(), latency_ms = $1, is_active = true
            WHERE node_id = $2
        `, [latency, NODE_ID]);
        
        await query(`
            INSERT INTO node_heartbeat (heartbeat_id, node_id, heartbeat_at, latency_ms)
            VALUES ($1, $2, NOW(), $3)
        `, [uuidv4(), NODE_ID, latency]);
        
        console.log('Heartbeat sent for master node', NODE_ID);
        console.log('Heartbeat latency (ms):', latency);
        console.log(`Sent at: ${new Date().toISOString()}`);
    } catch (error) {
        console.error('Error sending heartbeat:', error);
    }
}

async function updateCapacity() {
    try {
        const files = await fs.readdir(STORAGE_PATH);
        let usedBytes = 0;
        
        for (const file of files) {
            const stats = await fs.stat(path.join(STORAGE_PATH, file));
            usedBytes += stats.size;
        }
        
        const capacityResult = await query('SELECT total_bytes FROM node_capacity WHERE node_id = $1', [NODE_ID]);
        const totalBytes = capacityResult.rows[0]?.total_bytes || 12 * 1024 * 1024 * 1024;
        const availableBytes = totalBytes - usedBytes;
        
        await query(`
            UPDATE node_capacity 
            SET used_bytes = $1, available_bytes = $2, updated_at = NOW()
            WHERE node_id = $3
        `, [usedBytes, availableBytes, NODE_ID]);
        
        console.log(`Master Node ${NODE_ID} capacity updated.`);
        console.log('Available Bytes:', availableBytes);
        console.log('Used Bytes:', usedBytes);
    } catch (error) {
        console.error('Error updating capacity:', error);
    }
}

// API endpoints
// Enhanced health endpoint with database status
app.get('/health', async (req, res) => {
    try {
        const dbHealth = await checkDatabaseHealth();
        const poolStatus = {
            total: pool.totalCount,
            idle: pool.idleCount,
            waiting: pool.waitingCount
        };
        
        res.json({
            status: dbHealth.healthy ? 'Healthy' : 'Unhealthy',
            nodeId: NODE_ID,
            hostname: NODE_HOSTNAME,
            role: NODE_ROLE,
            database: {
                type: 'PostgreSQL',
                healthy: dbHealth.healthy,
                tables: dbHealth.tables || 0,
                reason: dbHealth.reason || 'OK'
            },
            connection_pool: poolStatus,
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        console.error('Health check error:', error);
        res.status(500).json({
            status: 'Error',
            nodeId: NODE_ID,
            error: error.message
        });
    }
});

// Storage nodes register with master node
app.post('/register-node', async (req, res) => {
    try {
        const { nodeId, apiEndpoint, nodeRole, hostname } = req.body;
        
        if (!nodeId || !apiEndpoint || !nodeRole || !hostname) {
            return res.status(400).json({ error: 'Missing required fields' });
        }
        
        await query(`
            INSERT INTO node (node_id, api_endpoint, node_role, hostname, is_active, uptimed_at, heartbeat_at)
            VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
            ON CONFLICT (node_id) DO UPDATE SET
                api_endpoint = EXCLUDED.api_endpoint,
                node_role = EXCLUDED.node_role,
                hostname = EXCLUDED.hostname,
                is_active = EXCLUDED.is_active
        `, [nodeId, apiEndpoint, nodeRole, hostname, true]);
        
        // Set default capacity for storage nodes
        if (nodeRole === 'STORAGE') {
            const defaultCapacity = 100 * 1024 * 1024 * 1024; // 100GB
            await query(`
                INSERT INTO node_capacity (node_id, total_bytes, used_bytes, available_bytes, updated_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (node_id) DO UPDATE SET
                    total_bytes = EXCLUDED.total_bytes,
                    updated_at = NOW()
            `, [nodeId, defaultCapacity, 0, defaultCapacity]);
        }
        
        console.log(`Node ${nodeId} registered as ${nodeRole}`);
        res.json({ success: true, message: 'Node registered successfully' });
    } catch (error) {
        console.error('Error registering node:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

// Storage nodes send heartbeats to master node
app.post('/node-heartbeat', async (req, res) => {
    try {
        const { nodeId, latency } = req.body;
        
        if (!nodeId) {
            return res.status(400).json({ error: 'Missing nodeId' });
        }
        
        const heartbeatLatency = latency || 0;
        await query(`
            UPDATE node 
            SET heartbeat_at = NOW(), latency_ms = $1, is_active = true
            WHERE node_id = $2
        `, [heartbeatLatency, nodeId]);
        
        await query(`
            INSERT INTO node_heartbeat (heartbeat_id, node_id, heartbeat_at, latency_ms)
            VALUES ($1, $2, NOW(), $3)
        `, [uuidv4(), nodeId, heartbeatLatency]);
        
        res.json({ success: true, message: 'Heartbeat recorded' });
    } catch (error) {
        console.error('Error recording heartbeat:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

// Cleanup old heartbeat records (runs every hour, keeps last 24 hours)
setInterval(async () => {
    try {
        const result = await query(`
            DELETE FROM node_heartbeat 
            WHERE heartbeat_at < NOW() - INTERVAL '24 hours'
        `);
        if (result.rowCount > 0) {
            console.log(`Cleaned up ${result.rowCount} old heartbeat records`);
        }
    } catch (error) {
        console.error('Error cleaning up heartbeats:', error);
    }
}, 3600000); // Run every hour

// Storage nodes update their capacity
app.post('/update-capacity', async (req, res) => {
    try {
        const { nodeId, totalBytes, usedBytes, availableBytes } = req.body;
        
        if (!nodeId) {
            return res.status(400).json({ error: 'Missing nodeId' });
        }
        
        await query(`
            UPDATE node_capacity 
            SET used_bytes = $1, available_bytes = $2, updated_at = NOW()
            WHERE node_id = $3
        `, [usedBytes || 0, availableBytes || totalBytes, nodeId]);
        
        res.json({ success: true, message: 'Capacity updated' });
    } catch (error) {
        console.error('Error updating capacity:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

// Get all nodes
app.get('/nodes', async (req, res) => {
    try {
        const result = await query(`
            SELECT n.*, c.total_bytes, c.used_bytes, c.available_bytes 
            FROM node n 
            LEFT JOIN node_capacity c ON n.node_id = c.node_id 
            ORDER BY n.node_role, n.hostname
        `);
        
        res.json(result.rows);
    } catch (error) {
        console.error('Error retrieving nodes:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

// Get specific node by ID
app.get('/nodes/:node_id', async (req, res) => {
    try {
        const { node_id } = req.params;
        
        const result = await query(`
            SELECT n.*, c.total_bytes, c.used_bytes, c.available_bytes 
            FROM node n 
            LEFT JOIN node_capacity c ON n.node_id = c.node_id 
            WHERE n.node_id = $1
        `, [node_id]);
        
        if (result.rows.length === 0) {
            return res.status(404).json({ error: 'Node not found' });
        }
        
        res.json(result.rows[0]);
    } catch (error) {
        console.error('Error retrieving node:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

// Enhanced database query endpoint with better error handling and security
// Helper function to serialize datetime objects for JSON response
function serializeRowsForJSON(rows) {
    return rows.map(row => {
        const serializedRow = {};
        for (const [key, value] of Object.entries(row)) {
            if (value instanceof Date) {
                serializedRow[key] = value.toISOString();
            } else {
                serializedRow[key] = value;
            }
        }
        return serializedRow;
    });
}

app.post('/query', async (req, res) => {
    try {
        const { sql, params = [], transaction = false } = req.body;
        
        console.log('=== Master Node Query Request ===');
        console.log('SQL:', sql);
        console.log('Params:', params);
        console.log('Transaction:', transaction);
        
        if (!sql) {
            return res.status(400).json({ error: 'SQL query required' });
        }
        
        // Enhanced security check with more comprehensive validation
        const sqlLower = sql.trim().toLowerCase();
        const allowedOperations = ['select', 'insert', 'update', 'delete'];
        const isAllowedOperation = allowedOperations.some(op => sqlLower.startsWith(op));
        
        if (!isAllowedOperation) {
            console.warn('Blocked unauthorized SQL operation:', sqlLower.substring(0, 50));
            return res.status(400).json({ 
                error: 'Only SELECT, INSERT, UPDATE, DELETE operations allowed',
                received_operation: sqlLower.split(' ')[0]
            });
        }
        
        // Block potentially dangerous operations
        const dangerousPatterns = [
            'drop table', 'drop database', 'alter table', 'create table',
            'truncate', 'grant', 'revoke', 'create user', 'drop user'
        ];
        
        for (const pattern of dangerousPatterns) {
            if (sqlLower.includes(pattern)) {
                console.warn('Blocked dangerous SQL pattern:', pattern);
                return res.status(400).json({ 
                    error: 'Dangerous SQL operation detected',
                    pattern: pattern
                });
            }
        }
        
        let result;
        
        if (transaction) {
            // Execute within transaction
            result = await withTransaction(async (client) => {
                return await query(sql, params, { client });
            });
        } else {
            // Execute as single query
            result = await query(sql, params);
        }
        
        console.log('Query executed successfully. Rows returned:', result.rows.length);
        
        res.json({ 
            success: true, 
            data: serializeRowsForJSON(result.rows),
            rowCount: result.rowCount,
            command: result.command 
        });
        
    } catch (error) {
        console.error('=== Database Query Error ===');
        console.error('Error:', error.message);
        console.error('Code:', error.code);
        console.error('Detail:', error.detail);
        
        // Provide more specific error information
        let errorResponse = {
            success: false,
            error: 'Database query error',
            details: error.message
        };
        
        // Add specific error codes for common issues
        if (error.code === '23505') { // Unique violation
            errorResponse.error = 'Duplicate entry violation';
            errorResponse.constraint = error.constraint;
        } else if (error.code === '23503') { // Foreign key violation
            errorResponse.error = 'Foreign key constraint violation';
            errorResponse.constraint = error.constraint;
        } else if (error.code === '42P01') { // Table doesn't exist
            errorResponse.error = 'Table does not exist';
        } else if (error.code === '42703') { // Column doesn't exist
            errorResponse.error = 'Column does not exist';
        }
        
        res.status(500).json(errorResponse);
    }
});

// File fragment management
// Note: Fragments are stored in FILE_FRAGMENTS (with segment_id) and FRAGMENT_LOCATION (with node_id)
// This endpoint is kept for backward compatibility but should use the proper schema
app.post('/fragments', async (req, res) => {
    try {
        // Backwards-compatible: accept either (segmentId + numFragment + bytes + contentHash)
        // or a storage-node confirmation containing fragmentId, bytes, nodeId, fragmentAddress
        const { segmentId, numFragment, bytes, contentHash } = req.body;
        const providedFragmentId = req.body.fragmentId;
        const nodeId = req.body.nodeId || req.body.node_id;
        const fragmentAddress = req.body.fragmentAddress || req.body.fragment_address;

        // If client provided a fragmentId, assume this is a storage-node confirmation
        if (providedFragmentId) {
            const fragmentId = providedFragmentId;

            // Skip registration for key fragments - they don't belong in fragment_location table
            // Key fragments are identified by checking if they correspond to encryption key storage
            const isKeyFragment = fragmentAddress && fragmentAddress.includes('/key_');
            
            if (!isKeyFragment) {
                // Insert fragment_location for the confirmed fragment write (file fragments only)
                if (nodeId && fragmentAddress) {
                    await query(`
                        INSERT INTO fragment_location (fragment_id, node_id, fragment_address, bytes, status, stored_at)
                        VALUES ($1, $2, $3, $4, 'ACTIVE', NOW())
                    `, [fragmentId, nodeId, fragmentAddress, bytes || 0]);
                }
            } else {
                console.log(`Skipping master node registration for key fragment: ${fragmentId}`);
            }

            return res.json({ success: true, fragmentId });
        }

        // Fallback: caller didn't provide fragmentId — preserve legacy behavior
        if (!segmentId || numFragment === undefined || !bytes || !contentHash) {
            return res.status(400).json({ error: 'Missing required fields: segmentId, numFragment, bytes, contentHash' });
        }

        const fragmentId = uuidv4();

        // Insert into file_fragments table
        await query(`
            INSERT INTO file_fragments (fragment_id, segment_id, num_fragment, bytes, content_hash, stored_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
        `, [fragmentId, segmentId, numFragment, bytes, contentHash]);

        // If nodeId and fragmentAddress provided, also insert into fragment_location (legacy callers)
        if (nodeId && fragmentAddress) {
            await query(`
                INSERT INTO fragment_location (fragment_id, node_id, fragment_address, bytes, status, stored_at)
                VALUES ($1, $2, $3, $4, 'ACTIVE', NOW())
            `, [fragmentId, nodeId, fragmentAddress, bytes]);
        }

        res.json({ success: true, fragmentId });
    } catch (error) {
        console.error('Error storing fragment info:', error);
        res.status(500).json({ error: 'Internal server error', details: error.message });
    }
});

// Get fragments by file_id (through segments and versions)
app.get('/fragments/:fileId', async (req, res) => {
    try {
        const { fileId } = req.params;
        const result = await query(`
            SELECT 
                ff.fragment_id, 
                ff.segment_id,
                ff.num_fragment, 
                ff.bytes, 
                ff.content_hash,
                fl.node_id, 
                fl.fragment_address,
                n.api_endpoint, 
                n.hostname 
            FROM file_objects fo
            JOIN file_versions fv ON fo.file_id = fv.file_id
            JOIN file_segments fs ON fv.version_id = fs.version_id
            JOIN file_fragments ff ON fs.segment_id = ff.segment_id
            LEFT JOIN fragment_location fl ON ff.fragment_id = fl.fragment_id
            LEFT JOIN node n ON fl.node_id = n.node_id
            WHERE fo.file_id = $1 
            ORDER BY ff.num_fragment
        `, [fileId]);
        
        res.json(result.rows);
    } catch (error) {
        console.error('Error retrieving fragments:', error);
        res.status(500).json({ error: 'Internal server error', details: error.message });
    }
});

// Enhanced master node status with comprehensive database information
app.get('/status', async (req, res) => {
    try {
        const nodeResult = await query(`
            SELECT n.*, c.total_bytes, c.used_bytes, c.available_bytes 
            FROM node n 
            LEFT JOIN node_capacity c ON n.node_id = c.node_id 
            WHERE n.node_id = $1
        `, [NODE_ID]);
        
        const nodeInfo = nodeResult.rows[0];
        
        // Get comprehensive statistics
        const [accountsResult, filesResult, fragmentsResult, nodesResult, activeNodesResult] = await Promise.all([
            query('SELECT COUNT(*) as count FROM account'),
            query('SELECT COUNT(*) as count FROM file_objects'),
            query('SELECT COUNT(*) as count FROM file_fragments'),
            query(`SELECT COUNT(*) as count FROM node WHERE node_role = 'STORAGE'`),
            query(`SELECT COUNT(*) as count FROM node WHERE node_role = 'STORAGE' AND is_active = true`)
        ]);
        
        const dbHealth = await checkDatabaseHealth();
        
        const stats = {
            accounts: parseInt(accountsResult.rows[0].count),
            files: parseInt(filesResult.rows[0].count),
            fragments: parseInt(fragmentsResult.rows[0].count),
            total_storage_nodes: parseInt(nodesResult.rows[0].count),
            active_storage_nodes: parseInt(activeNodesResult.rows[0].count)
        };
        
        res.json({
            master_node: {
                ...nodeInfo,
                uptime_seconds: Math.floor(process.uptime()),
                memory_usage: process.memoryUsage(),
                node_version: process.version
            },
            database: {
                type: 'PostgreSQL',
                healthy: dbHealth.healthy,
                status: dbHealth.healthy ? 'active' : 'inactive',
                tables: dbHealth.tables || 0,
                schema_version: 'complete',
                connection_pool: {
                    total: pool.totalCount,
                    idle: pool.idleCount,
                    waiting: pool.waitingCount
                }
            },
            statistics: stats,
            last_updated: new Date().toISOString()
        });
    } catch (error) {
        console.error('Error retrieving status:', error);
        res.status(500).json({ error: 'Internal server error', details: error.message });
    }
});

// Database statistics endpoint
app.get('/db/stats', async (req, res) => {
    try {
        // Get table sizes and row counts
        const tableStatsQuery = `
            SELECT 
                schemaname,
                tablename,
                attname,
                n_distinct,
                correlation
            FROM pg_stats 
            WHERE schemaname = 'public'
            ORDER BY tablename, attname;
        `;
        
        const tableSizesQuery = `
            SELECT 
                table_name,
                pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) as size,
                pg_relation_size(quote_ident(table_name)) as size_bytes
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY pg_relation_size(quote_ident(table_name)) DESC;
        `;
        
        const [tableStats, tableSizes] = await Promise.all([
            query(tableStatsQuery),
            query(tableSizesQuery)
        ]);
        
        res.json({
            table_statistics: tableStats.rows,
            table_sizes: tableSizes.rows,
            total_database_size: await query("SELECT pg_size_pretty(pg_database_size(current_database())) as size")
                .then(result => result.rows[0].size)
        });
    } catch (error) {
        console.error('Error retrieving database statistics:', error);
        res.status(500).json({ error: 'Internal server error', details: error.message });
    }
});

// Batch query endpoint for multiple operations
app.post('/query/batch', async (req, res) => {
    try {
        const { queries, transaction = true } = req.body;
        
        if (!Array.isArray(queries) || queries.length === 0) {
            return res.status(400).json({ error: 'Queries array is required and must not be empty' });
        }
        
        console.log(`Executing batch of ${queries.length} queries, transaction: ${transaction}`);
        
        if (transaction) {
            // Execute all queries in a single transaction
            const results = await withTransaction(async (client) => {
                const batchResults = [];
                for (let i = 0; i < queries.length; i++) {
                    const { sql, params = [] } = queries[i];
                    console.log(`Batch query ${i + 1}/${queries.length}: ${sql.substring(0, 50)}...`);
                    
                    const result = await query(sql, params, { client });
                    batchResults.push({
                        index: i,
                        success: true,
                        data: serializeRowsForJSON(result.rows),
                        rowCount: result.rowCount
                    });
                }
                return batchResults;
            });
            
            res.json({ success: true, results, transaction: true });
        } else {
            // Execute queries individually
            const results = [];
            for (let i = 0; i < queries.length; i++) {
                try {
                    const { sql, params = [] } = queries[i];
                    const result = await query(sql, params);
                    results.push({
                        index: i,
                        success: true,
                        data: result.rows,
                        rowCount: result.rowCount
                    });
                } catch (error) {
                    results.push({
                        index: i,
                        success: false,
                        error: error.message
                    });
                }
            }
            
            res.json({ success: true, results, transaction: false });
        }
        
    } catch (error) {
        console.error('Batch query error:', error);
        res.status(500).json({ error: 'Batch query error', details: error.message });
    }
});

// File metadata creation endpoint
app.post('/files', async (req, res) => {
    try {
        const { 
            account_id, 
            file_name, 
            file_size, 
            logical_path, 
            folder_id, 
            erasure_id,
            // Encryption support fields
            encryption_metadata,
            original_file_size,
            original_file_hash,
            is_encrypted,
            // SSS Key Storage fields
            key_storage_url,
            key_fragment_id
        } = req.body;
        
        if (!account_id || !file_name || !file_size || !logical_path) {
            return res.status(400).json({ error: 'Missing required fields: account_id, file_name, file_size, logical_path' });
        }
        
        const fileId = uuidv4();
        const versionId = uuidv4();
        
        // Create FILE_OBJECTS entry with encryption support
        await query(`
            INSERT INTO FILE_OBJECTS (
                FILE_ID, ACCOUNT_ID, FILE_NAME, FILE_SIZE, LOGICAL_PATH, FOLDER_ID, 
                IS_ENCRYPTED, ENCRYPTION_METADATA, ORIGINAL_FILE_SIZE, ORIGINAL_FILE_HASH, 
                key_storage_url, key_fragment_id, UPLOADED_AT
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
        `, [
            fileId, 
            account_id, 
            file_name, 
            file_size, 
            logical_path, 
            folder_id || null,
            is_encrypted || false,
            encryption_metadata ? JSON.stringify(encryption_metadata) : null,
            original_file_size || null,
            original_file_hash || null,
            key_storage_url || null,
            key_fragment_id || null
        ]);
        
        // Create FILE_VERSIONS entry - using BYTES instead of FILE_SIZE
        await query(`
            INSERT INTO FILE_VERSIONS (VERSION_ID, FILE_ID, ERASURE_ID, BYTES, CONTENT_HASH, UPLOADED_AT)
            VALUES ($1, $2, $3, $4, $5, NOW())
        `, [versionId, fileId, erasure_id || 'MEDIUM', file_size, 'pending_hash']);
        
        res.json({ 
            success: true, 
            fileId: fileId, 
            versionId: versionId, 
            message: 'File metadata created successfully' 
        });
    } catch (error) {
        console.error('Error creating file metadata:', error);
        res.status(500).json({ error: 'Internal server error', details: error.message });
    }
});

// Key shares storage endpoint (Shamir's Secret Sharing)
app.post('/key-shares', async (req, res) => {
    try {
        const { version_id, encryption_key, key_shares } = req.body;
        
        if (!version_id || !encryption_key || !key_shares || !Array.isArray(key_shares)) {
            return res.status(400).json({ 
                error: 'Missing required fields: version_id, encryption_key, key_shares (array)' 
            });
        }
        
        const keyId = uuidv4();
        
        // Store encryption key in FILE_KEYS table
        await query(`
            INSERT INTO FILE_KEYS (KEY_ID, VERSION_ID, ENCRYPTION_KEY, KEY_CREATED_AT)
            VALUES ($1, $2, $3, NOW())
        `, [keyId, version_id, encryption_key]);
        
        console.log(`Created FILE_KEYS entry: ${keyId} for version ${version_id}`);
        
        // Get available storage nodes for key share distribution
        const nodesResult = await query(`
            SELECT node_id, api_endpoint, hostname FROM (
                SELECT DISTINCT ON (hostname) node_id, api_endpoint, hostname, heartbeat_at
                FROM node
                WHERE node_role = 'STORAGE' AND is_active = true
                ORDER BY hostname, heartbeat_at DESC
            ) t
            WHERE t.heartbeat_at > NOW() - INTERVAL '90 seconds'
            ORDER BY random()
            LIMIT $1
        `, [key_shares.length]);
        
        if (nodesResult.rows.length < key_shares.length) {
            // Rollback FILE_KEYS if we can't distribute shares
            await query('DELETE FROM FILE_KEYS WHERE KEY_ID = $1', [keyId]);
            return res.status(503).json({ 
                error: 'Insufficient storage nodes for key shares', 
                available: nodesResult.rows.length, 
                required: key_shares.length 
            });
        }
        
        // Store key shares across storage nodes
        const storedShares = [];
        
        for (let i = 0; i < key_shares.length; i++) {
            const share = key_shares[i];
            const node = nodesResult.rows[i];
            const shareId = uuidv4();
            
            try {
                // Store key share as a fragment in storage node
                const storeResponse = await axios.post(`${node.api_endpoint}/fragments`, {
                    fragmentId: shareId,
                    data: share.share_data,
                    bytes: Buffer.from(share.share_data, 'base64').length,
                    contentHash: `keyshare_${keyId}_${share.share_index}`,
                    fileId: `keyshare_${keyId}`,
                    fragmentOrder: share.share_index
                }, {
                    headers: { 'Content-Type': 'application/json' },
                    timeout: 10000
                });
                
                if (storeResponse.status === 200 || storeResponse.status === 201) {
                    const fragmentAddress = storeResponse.data.fragmentAddress || `key_share_${shareId}`;
                    
                    // Record key share location in database with fragment ID
                    await query(`
                        INSERT INTO KEY_SHARE (KEY_ID, KEY_SHARE_ID, NODE_ID, SHARE_BYTES, SHARE_ADDRESS, FRAGMENT_ID, CREATED_AT)
                        VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    `, [
                        keyId,
                        share.share_index,
                        node.node_id,
                        Buffer.from(share.share_data, 'base64').length,
                        fragmentAddress,
                        shareId  // Store the fragment UUID for retrieval
                    ]);
                    
                    storedShares.push({
                        shareIndex: share.share_index,
                        nodeId: node.node_id,
                        shareAddress: fragmentAddress
                    });
                    
                    console.log(`Stored key share ${share.share_index} on ${node.node_id}`);
                }
            } catch (error) {
                console.error(`Failed to store key share ${share.share_index} on ${node.node_id}:`, error.message);
                // Continue with other shares - some shares might still succeed
            }
        }
        
        if (storedShares.length === 0) {
            // Cleanup if no shares were stored
            await query('DELETE FROM FILE_KEYS WHERE KEY_ID = $1', [keyId]);
            return res.status(500).json({ 
                error: 'Failed to store any key shares',
                details: 'All storage node requests failed'
            });
        }
        
        res.json({ 
            success: true,
            keyId: keyId,
            sharesStored: storedShares.length,
            totalShares: key_shares.length,
            shares: storedShares,
            message: `Successfully stored ${storedShares.length}/${key_shares.length} key shares`
        });
        
    } catch (error) {
        console.error('Error storing key shares:', error);
        res.status(500).json({ error: 'Internal server error', details: error.message });
    }
});

// Get key shares for a file version (for download/decryption)
app.get('/key-shares/:version_id', async (req, res) => {
    try {
        const { version_id } = req.params;
        
        if (!version_id) {
            return res.status(400).json({ error: 'Missing required parameter: version_id' });
        }
        
        // Get key_id from FILE_KEYS table
        const keyResult = await query(`
            SELECT KEY_ID FROM FILE_KEYS WHERE VERSION_ID = $1
        `, [version_id]);
        
        if (keyResult.rows.length === 0) {
            return res.status(404).json({ 
                error: 'No encryption key found for this file version',
                version_id: version_id
            });
        }
        
        const keyId = keyResult.rows[0].key_id;
        
        // Get all key shares for this key
        const sharesResult = await query(`
            SELECT ks.KEY_SHARE_ID, ks.NODE_ID, ks.SHARE_BYTES, ks.SHARE_ADDRESS, ks.FRAGMENT_ID,
                   n.API_ENDPOINT, n.IS_ACTIVE
            FROM KEY_SHARE ks
            JOIN NODE n ON ks.NODE_ID = n.NODE_ID
            WHERE ks.KEY_ID = $1
            ORDER BY ks.KEY_SHARE_ID
        `, [keyId]);
        
        if (sharesResult.rows.length === 0) {
            return res.status(404).json({ 
                error: 'No key shares found for this encryption key',
                key_id: keyId
            });
        }
        
        const shares = sharesResult.rows.map(row => ({
            key_share_id: parseInt(row.key_share_id),
            node_id: row.node_id,
            share_bytes: parseInt(row.share_bytes),
            share_address: row.share_address,
            fragment_id: row.fragment_id,  // Include fragment UUID for retrieval
            api_endpoint: row.api_endpoint,
            is_active: row.is_active
        }));
        
        const activeShares = shares.filter(s => s.is_active);
        
        res.json({
            success: true,
            key_id: keyId,
            version_id: version_id,
            total_shares: shares.length,
            active_shares: activeShares.length,
            shares: shares
        });
        
    } catch (error) {
        console.error('Error retrieving key shares:', error);
        res.status(500).json({ error: 'Internal server error', details: error.message });
    }
});

// File fragment distribution endpoint
app.post('/file-fragments', async (req, res) => {
    try {
        const { version_id, segment_id, fragment_data, erasure_id } = req.body;
        
        if (!version_id || !segment_id || !fragment_data || !Array.isArray(fragment_data)) {
            return res.status(400).json({ error: 'Missing required fields: version_id, segment_id, fragment_data (array)' });
        }
        
        // Create FILE_SEGMENTS entry
        await query(`
            INSERT INTO FILE_SEGMENTS (SEGMENT_ID, VERSION_ID, ERASURE_ID, NUM_SEGMENT, BYTES, CONTENT_HASH, STORED_AT)
            VALUES ($1, $2, $3, 0, $4, $5, NOW())
        `, [segment_id, version_id, erasure_id || 'MEDIUM', 
            fragment_data.reduce((total, frag) => total + frag.bytes, 0), 'pending']);
        
        // Get available storage nodes.
        // Only consider nodes that have a recent heartbeat (healthy) and de-duplicate
        // by hostname (use the most-recent registration per hostname). This avoids
        // selecting nodes that were shut down but still have rows in the DB.
        const nodesResult = await query(`
            SELECT node_id, api_endpoint, hostname FROM (
                SELECT DISTINCT ON (hostname) node_id, api_endpoint, hostname, heartbeat_at
                FROM node
                WHERE node_role = 'STORAGE' AND is_active = true
                ORDER BY hostname, heartbeat_at DESC
            ) t
            WHERE t.heartbeat_at > NOW() - INTERVAL '90 seconds'
            ORDER BY random()
            LIMIT $1
        `, [fragment_data.length]);
        
        if (nodesResult.rows.length < fragment_data.length) {
            return res.status(503).json({ 
                error: 'Insufficient storage nodes', 
                available: nodesResult.rows.length, 
                required: fragment_data.length 
            });
        }
        
        const distributedFragments = [];
        
        // Create fragments and assign to nodes
        for (let i = 0; i < fragment_data.length; i++) {
            const fragment = fragment_data[i];
            const node = nodesResult.rows[i];
            const fragmentId = uuidv4();
            
            // Insert only FILE_FRAGMENTS here. Do NOT insert FRAGMENT_LOCATION yet;
            // storage nodes will confirm the write and notify master with the
            // final fragment address (logical object key). This avoids stale
            // DB rows when storage writes fail or are delayed.
            await query(`
                INSERT INTO FILE_FRAGMENTS (FRAGMENT_ID, SEGMENT_ID, NUM_FRAGMENT, BYTES, CONTENT_HASH, STORED_AT)
                VALUES ($1, $2, $3, $4, $5, NOW())
            `, [fragmentId, segment_id, fragment.num_fragment, fragment.bytes, fragment.content_hash]);

            distributedFragments.push({
                fragmentId: fragmentId,
                nodeId: node.node_id,
                nodeEndpoint: node.api_endpoint,
                fragmentOrder: fragment.num_fragment,
                bytes: fragment.bytes
            });
        }
        
        res.json({ 
            success: true, 
            fragments: distributedFragments,
            message: 'Fragment distribution planned successfully'
        });
    } catch (error) {
        console.error('Error distributing fragments:', error);
        res.status(500).json({ error: 'Internal server error', details: error.message });
    }
});

// Erasure profiles endpoint
app.get('/erasure-profiles/:id', async (req, res) => {
    try {
        const { id } = req.params;
        
        // Query database for erasure profile
        const result = await query(
            'SELECT erasure_id, k, m, bytes, notes FROM erasure_profile WHERE UPPER(erasure_id) = UPPER($1)',
            [id]
        );
        
        if (result.rows.length === 0) {
            // Get available profiles for error message
            const availableResult = await query('SELECT erasure_id FROM erasure_profile ORDER BY erasure_id');
            const available = availableResult.rows.map(row => row.erasure_id);
            return res.status(404).json({ 
                error: 'Erasure profile not found', 
                available: available 
            });
        }
        
        const profile = result.rows[0];
        
        res.json({
            success: true,
            profile_id: profile.erasure_id,
            k: parseInt(profile.k),
            m: parseInt(profile.m),
            bytes: parseInt(profile.bytes),
            total_fragments: parseInt(profile.k) + parseInt(profile.m),
            redundancy_ratio: parseInt(profile.m) / parseInt(profile.k),
            description: profile.notes || `${profile.k}+${profile.m} Reed-Solomon encoding`
        });
    } catch (error) {
        console.error('Error getting erasure profile:', error);
        res.status(500).json({ error: 'Internal server error', details: error.message });
    }
});

// List all available erasure profiles
app.get('/erasure-profiles', async (req, res) => {
    try {
        // Query database for all erasure profiles
        const result = await query(
            'SELECT erasure_id, k, m, bytes, notes FROM erasure_profile ORDER BY erasure_id'
        );
        
        const profileList = result.rows.map(profile => {
            const k = parseInt(profile.k);
            const m = parseInt(profile.m);
            const bytes = parseInt(profile.bytes);
            
            return {
                profile_id: profile.erasure_id,
                k: k,
                m: m,
                bytes: bytes,
                description: profile.notes || `${k}+${m} Reed-Solomon encoding, can survive ${m} failures`,
                total_fragments: k + m,
                redundancy_ratio: m / k
            };
        });
        
        res.json({ success: true, profiles: profileList });
    } catch (error) {
        console.error('Error listing erasure profiles:', error);
        res.status(500).json({ error: 'Internal server error', details: error.message });
    }
});

// Get files for an account
app.get('/files/:accountId', async (req, res) => {
    try {
        const { accountId } = req.params;
        const result = await query(`
            SELECT 
                fo.file_id,
                fo.file_name,
                fo.file_size,
                fo.logical_path,
                fo.uploaded_at,
                fo.is_encrypted,
                fo.original_file_size,
                fo.original_file_hash,
                fv.version_id,
                fv.erasure_id,
                fv.content_hash
            FROM FILE_OBJECTS fo
            JOIN FILE_VERSIONS fv ON fo.file_id = fv.file_id
            WHERE fo.account_id = $1
            ORDER BY fo.uploaded_at DESC
        `, [accountId]);
        
        res.json({
            success: true,
            files: result.rows
        });
    } catch (error) {
        console.error('Error retrieving files:', error);
        res.status(500).json({ error: 'Internal server error', details: error.message });
    }
});

// Get file info by file ID
app.get('/files/info/:fileId', async (req, res) => {
    try {
        const { fileId } = req.params;
        const result = await query(`
            SELECT 
                fo.file_id,
                fo.account_id,
                fo.file_name,
                fo.file_size,
                fo.logical_path,
                fo.uploaded_at,
                fo.is_encrypted,
                fo.encryption_metadata,
                fo.original_file_size,
                fo.original_file_hash,
                fo.key_storage_url,
                fo.key_fragment_id,
                fv.version_id,
                fv.erasure_id,
                fv.content_hash
            FROM FILE_OBJECTS fo
            JOIN FILE_VERSIONS fv ON fo.file_id = fv.file_id
            WHERE fo.file_id = $1
        `, [fileId]);
        
        if (result.rows.length === 0) {
            return res.status(404).json({ error: 'File not found' });
        }
        
        const fileData = result.rows[0];
        
        // Parse encryption_metadata if it exists
        if (fileData.encryption_metadata) {
            try {
                fileData.encryption_metadata = JSON.parse(fileData.encryption_metadata);
            } catch (e) {
                console.warn('Failed to parse encryption_metadata JSON:', e);
                fileData.encryption_metadata = null;
            }
        }
        
        res.json({
            success: true,
            file: fileData
        });
    } catch (error) {
        console.error('Error retrieving file info:', error);
        res.status(500).json({ error: 'Internal server error', details: error.message });
    }
});

// Create repair job
app.post('/repair-jobs', async (req, res) => {
    try {
        const { version_id, reason, priority, fragments_needed, fragments_available } = req.body;
        
        if (!version_id) {
            return res.status(400).json({ error: 'version_id is required' });
        }
        
        // Check if repair job already exists
        const existingJob = await query(`
            SELECT job_id FROM REPAIR_JOBS 
            WHERE version_id = $1 
            AND status IN ('PENDING', 'IN_PROGRESS')
            LIMIT 1
        `, [version_id]);
        
        if (existingJob.rows.length > 0) {
            return res.status(200).json({ 
                message: 'Repair job already exists',
                job_id: existingJob.rows[0].job_id,
                created: false
            });
        }
        
        // Create new repair job
        const job_id = uuidv4();
        await query(`
            INSERT INTO REPAIR_JOBS 
            (JOB_ID, VERSION_ID, REASON, STATUS, PRIORITY, 
             FRAGMENTS_NEEDED, FRAGMENTS_AVAILABLE, CREATED_AT, UPDATED_AT)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
        `, [
            job_id,
            version_id,
            reason || 'Lazy repair triggered',
            'PENDING',
            priority || 5,
            fragments_needed || 0,
            fragments_available || 0
        ]);
        
        console.log(`✅ Created repair job ${job_id} for version ${version_id}`);
        
        res.status(201).json({ 
            message: 'Repair job created successfully',
            job_id: job_id,
            created: true
        });
        
    } catch (error) {
        console.error('Error creating repair job:', error);
        res.status(500).json({ error: 'Failed to create repair job', details: error.message });
    }
});

// Key share health check endpoint
app.get('/key-shares/health/:version_id', async (req, res) => {
    const { version_id } = req.params;
    
    try {
        // Get key_id for this version
        const keyResult = await pool.query(
            'SELECT KEY_ID FROM FILE_KEYS WHERE VERSION_ID = $1',
            [version_id]
        );
        
        if (keyResult.rows.length === 0) {
            return res.status(404).json({ error: 'No encryption key found for this version' });
        }
        
        const key_id = keyResult.rows[0].key_id;
        
        // Get all key shares with node status
        const sharesResult = await pool.query(`
            SELECT ks.KEY_ID, ks.KEY_SHARE_ID, ks.NODE_ID, ks.FRAGMENT_ID,
                   n.IS_ACTIVE, n.NODE_ROLE
            FROM KEY_SHARE ks
            LEFT JOIN NODE n ON ks.NODE_ID = n.NODE_ID
            WHERE ks.KEY_ID = $1
            ORDER BY ks.KEY_SHARE_ID
        `, [key_id]);
        
        const shares = sharesResult.rows;
        const active_shares = shares.filter(s => s.is_active);
        const inactive_shares = shares.filter(s => !s.is_active);
        
        const threshold = 5; // 5-of-7 threshold
        const health_status = {
            key_id: key_id,
            version_id: version_id,
            total_shares: shares.length,
            active_shares: active_shares.length,
            inactive_shares: inactive_shares.length,
            threshold_required: threshold,
            can_reconstruct: active_shares.length >= threshold,
            repair_needed: inactive_shares.length > 0,
            health: active_shares.length >= threshold ? 
                    (inactive_shares.length > 0 ? 'degraded' : 'healthy') : 
                    'critical',
            shares: shares.map(s => ({
                share_id: s.key_share_id,
                node_id: s.node_id,
                is_active: s.is_active,
                fragment_id: s.fragment_id
            }))
        };
        
        res.json(health_status);
    } catch (error) {
        console.error('Error checking key share health:', error);
        res.status(500).json({ error: 'Failed to check key share health', details: error.message });
    }
});

// Trigger key share repair for a specific version
app.post('/key-shares/repair/:version_id', async (req, res) => {
    const { version_id } = req.params;
    
    try {
        // Create a repair job that includes key share repair
        const jobId = uuidv4();
        
        await pool.query(`
            INSERT INTO REPAIR_JOBS 
            (JOB_ID, VERSION_ID, REASON, PRIORITY, FRAGMENTS_NEEDED, FRAGMENTS_AVAILABLE, STATUS)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        `, [
            jobId,
            version_id,
            'Manual key share repair triggered',
            10, // High priority
            0,  // Not for fragments
            0,
            'PENDING'
        ]);
        
        res.json({
            success: true,
            job_id: jobId,
            message: 'Key share repair job created. The repair worker will process it shortly.'
        });
    } catch (error) {
        console.error('Error creating key share repair job:', error);
        res.status(500).json({ error: 'Failed to create repair job', details: error.message });
    }
});

// Graceful shutdown with proper database cleanup
process.on('SIGTERM', async () => {
    console.log('Shutting down master node gracefully...');
    try {
        // Mark node as inactive
        await query('UPDATE node SET is_active = false WHERE node_id = $1', [NODE_ID]);
        console.log('Node marked as inactive in database');
        
        // Close all database connections
        await pool.end();
        console.log('Database connection pool closed');
        
    } catch (error) {
        console.error('Error during shutdown:', error);
    } finally {
        process.exit(0);
    }
});

process.on('SIGINT', async () => {
    console.log('Received SIGINT, shutting down gracefully...');
    process.emit('SIGTERM');
});

async function startServer() {
    try {
        // Initialize database connection first
        await initializeDatabase();
        
        // Check database health before starting
        const dbHealth = await checkDatabaseHealth();
        if (!dbHealth.healthy) {
            console.warn('Database health check failed:', dbHealth.reason);
            console.warn('Continuing startup, but some features may not work properly');
        } else {
            console.log(`Database health check passed. Found ${dbHealth.tables} tables.`);
        }
        
        // Initialize master node in database
        await initialiseDB();
        
        // Start periodic tasks
        setInterval(heartbeat, HEARTBEAT_INTERVAL);
        setInterval(updateCapacity, HEARTBEAT_INTERVAL * 6);
        
        // Start the server
        app.listen(NODE_PORT, '0.0.0.0', () => {
            console.log('=================================');
            console.log('🚀 Master Node Server Started');
            console.log('=================================');
            console.log(`Port: ${NODE_PORT}`);
            console.log(`Hostname: ${NODE_HOSTNAME}`);
            console.log(`API Endpoint: http://${NODE_HOSTNAME}:${NODE_PORT}`);
            console.log(`Database: PostgreSQL`);
            console.log(`Pool Size: ${pool.options.max} connections`);
            console.log('Health Check: /health');
            console.log('Query Endpoint: /query');
            console.log('=================================');
        });
        
    } catch (error) {
        console.error('Failed to start master node server:', error);
        process.exit(1);
    }
}

startServer().catch((error) => {
    console.error('Error starting master node server:', error);
    process.exit(1);
});

