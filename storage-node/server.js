const express = require('express');
const axios = require('axios');
const {v4: uuidv4} = require('uuid');
const fs = require('fs').promises;
const path = require('path');
const os = require('os');
const app = express();

// Get container's IP address on the overlay network
function getContainerIP() {
    const interfaces = os.networkInterfaces();
    
    // Look for the overlay network interface
    for (const name of Object.keys(interfaces)) {
        for (const iface of interfaces[name]) {
            // Skip internal (loopback) and IPv6 addresses
            if (!iface.internal && iface.family === 'IPv4') {
                // Skip Docker bridge networks (172.17.x.x) - these are not accessible from other containers
                if (!iface.address.startsWith('172.17.')) {
                    console.log(`Found overlay network IP: ${iface.address} on interface ${name}`);
                    return iface.address;
                }
            }
        }
    }
    
    console.warn('Could not find overlay network IP, falling back to hostname');
    return null; // Fallback to hostname if IP not found
}

// Configure Express to handle large payloads (up to 200MB)
app.use(express.json({ limit: '200mb', parameterLimit: 1000000 }));
app.use(express.urlencoded({ limit: '200mb', extended: true, parameterLimit: 1000000 }));

// Increase timeout for large uploads
app.use((req, res, next) => {
    req.setTimeout(600000); // 10 minutes
    res.setTimeout(600000); // 10 minutes
    next();
});

// Master node connection instead of direct database
const MASTER_NODE_HOST = process.env.MASTER_NODE_HOST || 'master_node';
const MASTER_NODE_PORT = process.env.MASTER_NODE_PORT || 3000;
const MASTER_NODE_URL = `http://${MASTER_NODE_HOST}:${MASTER_NODE_PORT}`;

// Get container IP for registration - THIS IS THE KEY FIX!
const CONTAINER_IP = getContainerIP();
// CRITICAL FIX: Use NODE_HOSTNAME env var FIRST, fallback to IP, then UUID
const NODE_HOSTNAME = process.env.NODE_HOSTNAME || CONTAINER_IP || `storage-node-${uuidv4().slice(0, 8)}`;

// CRITICAL FIX: Use hostname as NODE_ID to prevent duplicate registrations on restart
// This ensures the same physical node always has the same ID
const NODE_ID = process.env.NODE_ID || NODE_HOSTNAME;

const NODE_PORT = process.env.NODE_PORT || 3000;
const NODE_ROLE = process.env.NODE_ROLE || 'STORAGE';

// Use a logical objects folder for fragment objects. This makes addresses
// portable and easier to migrate to object storage later.
const STORAGE_PATH = process.env.STORAGE_PATH || '/data/objects';
const HEARTBEAT_INTERVAL = parseInt(process.env.HEARTBEAT_INTERVAL) || 10000;

async function registerWithMaster(){
    try {
        // Use IP address for API endpoint instead of hostname!
        const apiEndpoint = `http://${NODE_HOSTNAME}:${NODE_PORT}`;
        
        console.log(`Registering with master node...`);
        console.log(`API Endpoint: ${apiEndpoint}`);
        console.log(`Node ID: ${NODE_ID}`);
        
        const response = await axios.post(`${MASTER_NODE_URL}/register-node`, {
            nodeId: NODE_ID,
            apiEndpoint: apiEndpoint,
            nodeRole: NODE_ROLE,
            hostname: NODE_HOSTNAME
        });
        
        if (response.data.success) {
            console.log(`✅ Storage Node ${NODE_ID} registered with master node.`);
            console.log('Hostname/IP:', NODE_HOSTNAME);
            console.log('Role:', NODE_ROLE);
            console.log('Master Node:', MASTER_NODE_URL);
        } else {
            throw new Error('Failed to register with master node');
        }
    } catch (error) {
        console.error('Error registering with master node:', error.message);
        console.log('Retrying in 5 seconds...');
        setTimeout(registerWithMaster, 5000);
    }
}

async function heartbeat(){
    try{
        const startTime = Date.now();
        
        const response = await axios.post(`${MASTER_NODE_URL}/node-heartbeat`, {
            nodeId: NODE_ID,
            latency: 0  // Will be calculated on return
        });

        const latency = Date.now() - startTime;  // Actual round-trip time
        
        if (response.data.success) {
            console.log('Heartbeat sent for storage node', NODE_ID);
            console.log('Heartbeat latency (ms):', latency);
            console.log(`Sent at: ${new Date().toISOString()}`);
        }
    } catch (error) {
        console.error('Error sending heartbeat to master node:', error.message);
    }
}

async function updateCapacity(){
    try {
        const usedBytes = await getDirectorySize(STORAGE_PATH);
        const totalBytes = 100 * 1024 * 1024 * 1024; // 100GB default
        const availableBytes = totalBytes - usedBytes;

        // Send capacity update to master node
        try {
            await axios.post(`${MASTER_NODE_URL}/update-capacity`, {
                nodeId: NODE_ID,
                totalBytes: totalBytes,
                usedBytes: usedBytes,
                availableBytes: availableBytes
            });
        } catch (error) {
            console.error('Error updating capacity with master node:', error.message);
        }

        console.log(`Storage Node ${NODE_ID} capacity updated.`);
        console.log(`Available Bytes: ${availableBytes}`);
        console.log(`Used Bytes: ${usedBytes}`);
    } catch (error) {
        console.error('Error updating node capacity:', error);
    }
}

app.get('/health', (req, res) => {
    res.json({
        status: 'Healthy',
        nodeId: NODE_ID,
        hostname: NODE_HOSTNAME,
        role: NODE_ROLE,
    });
});

app.post('/fragments', async (req, res) => {
    try {
        const { fragmentId, data, bytes, contentHash } = req.body;
        if (!fragmentId || !data) {
            return res.status(400).json({ error: 'Missing fragmentId or data' });
        }

        // Decide object key — keep it deterministic so we can locate fragments later
        const fileId = req.body.fileId || 'unknown';
        const fragmentOrder = req.body.fragmentOrder !== undefined ? req.body.fragmentOrder : '0';
        const key = path.join(fileId.toString(), `${fragmentOrder}_${fragmentId}.bin`);
        const objectPath = path.join(STORAGE_PATH, key);

        // Ensure parent directory exists
        await fs.mkdir(path.dirname(objectPath), { recursive: true });

        // Store fragment locally as an "object"
        await fs.writeFile(objectPath, Buffer.from(data, 'base64'));

        console.log(`✅ Fragment ${fragmentId} stored at ${objectPath}`);

        // Notify master node about fragment storage with logical object address
        const fragmentAddress = `objects/${key}`; // logical address; master stores this
        try {
            await axios.post(`${MASTER_NODE_URL}/fragments`, {
                fragmentId: fragmentId,
                nodeId: NODE_ID,
                fragmentAddress: fragmentAddress,
                bytes: bytes || Buffer.from(data, 'base64').length,
                contentHash: contentHash || 'unknown',
                fileId: fileId,
                fragmentOrder: fragmentOrder
            });
        } catch (error) {
            console.error('Error notifying master node:', error.message);
            // Continue anyway - fragment is stored locally
        }

        await updateCapacity();
        res.json({
            success: true,
            fragmentId: fragmentId,
            nodeId: NODE_ID,
            path: objectPath,
            logicalAddress: fragmentAddress
        });
    } catch (error) {
        console.error('Error storing fragment:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

// List all fragments stored on this node
// Recursively list fragment files under STORAGE_PATH
async function listFragmentFiles(dir) {
    const results = [];
    try {
        const entries = await fs.readdir(dir, { withFileTypes: true });
        for (const entry of entries) {
            const fullPath = path.join(dir, entry.name);
            if (entry.isDirectory()) {
                const sub = await listFragmentFiles(fullPath);
                results.push(...sub);
            } else if (entry.isFile() && entry.name.endsWith('.bin')) {
                results.push(fullPath);
            }
        }
    } catch (err) {
        // ignore directory not found
    }
    return results;
}

app.get('/fragments', async (req, res) => {
    try {
        const files = await listFragmentFiles(STORAGE_PATH);
        const fragments = [];

        for (const fragmentPath of files) {
            const file = path.basename(fragmentPath);
            const fragmentId = file.replace('.bin', '').split('_').slice(-1)[0];
            try {
                const stats = await fs.stat(fragmentPath);
                fragments.push({
                    fragmentId: fragmentId,
                    bytes: stats.size,
                    storedAt: stats.mtime.toISOString(),
                    path: fragmentPath
                });
            } catch (error) {
                console.error(`Error getting stats for fragment ${fragmentId}:`, error.message);
            }
        }

        res.json({
            success: true,
            nodeId: NODE_ID,
            fragmentCount: fragments.length,
            fragments: fragments
        });
    } catch (error) {
        console.error('Error listing fragments:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

app.get('/fragments/:fragmentId', async (req, res) => {
    try {
        const { fragmentId } = req.params;

        // Search recursively for the fragment file (it may be stored under fileId/<order>_<fragmentId>.bin)
        const files = await listFragmentFiles(STORAGE_PATH);
        let found = null;
        for (const f of files) {
            const name = path.basename(f);
            if (name === `${fragmentId}.bin` || name.endsWith(`_${fragmentId}.bin`)) {
                found = f;
                break;
            }
        }

        if (!found) {
            return res.status(404).json({ error: 'Fragment not found' });
        }

        const data = await fs.readFile(found);
        res.json({
            success: true,
            fragmentId: fragmentId,
            data: data.toString('base64'),
            bytes: data.length,
            path: found
        });
    } catch (error) {
        console.error('Error retrieving fragment:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

app.delete('/fragments/:fragmentId', async (req, res) => {
    try {
        const { fragmentId } = req.params;

        const files = await listFragmentFiles(STORAGE_PATH);
        let found = null;
        for (const f of files) {
            const name = path.basename(f);
            if (name === `${fragmentId}.bin` || name.endsWith(`_${fragmentId}.bin`)) {
                found = f;
                break;
            }
        }

        if (!found) {
            return res.status(404).json({ error: 'Fragment not found' });
        }

        try {
            await fs.unlink(found);

            // Notify master node about fragment deletion
            try {
                await axios.delete(`${MASTER_NODE_URL}/fragments/${fragmentId}`);
            } catch (error) {
                console.error('Error notifying master node:', error.message);
            }

            await updateCapacity();
            res.json({ success: true, fragmentId: fragmentId });
        } catch (error) {
            throw error;
        }
    } catch (error) {
        console.error('Error deleting fragment:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

app.get('/status', async (req, res) => {
    try {
        const storageUsed = await getDirectorySize(STORAGE_PATH);
        const totalCapacity = 100 * 1024 * 1024 * 1024; // 100GB
        
        const storageInfo = {
            nodeId: NODE_ID,
            nodeType: 'storage',
            status: 'active',
            storageUsed: storageUsed,
            capacity: totalCapacity,
            address: `http://${NODE_HOSTNAME}:${NODE_PORT}`,
            lastUpdated: new Date().toISOString()
        };
        
        res.json(storageInfo);
    } catch (error) {
        console.error('Error retrieving node status:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

// Helper function to get directory size
async function getDirectorySize(dirPath) {
    let size = 0;
    try {
        const files = await fs.readdir(dirPath);
        for (const file of files) {
            const filePath = path.join(dirPath, file);
            const stats = await fs.stat(filePath);
            if (stats.isFile()) {
                size += stats.size;
            } else if (stats.isDirectory()) {
                size += await getDirectorySize(filePath);
            }
        }
    } catch (error) {
        // Directory might not exist yet
    }
    return size;
}

process.on('SIGTERM', async () => {
    console.log('Shutting down node...');
    try {
        await axios.post(`${MASTER_NODE_URL}/nodes/deregister`, {
            nodeId: NODE_ID
        });
    } catch (error) {
        console.error('Error deregistering from master node:', error);
    }
    process.exit(0);
});

async function startServer(){
    console.log('=================================');
    console.log('🚀 Storage Node Starting');
    console.log('=================================');
    console.log(`Node ID: ${NODE_ID}`);
    console.log(`Container IP: ${CONTAINER_IP || 'Not found'}`);
    console.log(`Hostname: ${NODE_HOSTNAME}`);
    console.log(`Port: ${NODE_PORT}`);
    console.log(`Master Node: ${MASTER_NODE_URL}`);
    console.log('=================================');
    
    await registerWithMaster();
    
    // Ensure storage directory exists
    try {
        await fs.mkdir(STORAGE_PATH, { recursive: true });
        console.log(`Storage directory created/verified: ${STORAGE_PATH}`);
    } catch (error) {
        console.error(`Error creating storage directory: ${error.message}`);
    }
    
    setInterval(heartbeat, HEARTBEAT_INTERVAL);
    setInterval(updateCapacity, HEARTBEAT_INTERVAL * 6);
    app.listen(NODE_PORT, '0.0.0.0', () => {
        console.log(`✅ Storage Node server running on ${NODE_HOSTNAME}:${NODE_PORT}`);
        console.log(`Connected to Master Node: ${MASTER_NODE_URL}`);
    });
}

startServer().catch((error) => {
    console.error('Error starting node server:', error);
    process.exit(1);
});