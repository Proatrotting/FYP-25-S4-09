const express = require('express');
const axios = require('axios');
const {v4: uuidv4} = require('uuid');
const fs = require('fs').promises;
const path = require('path');
const os = require('os');
const app = express();

// ============================================================================
// CRITICAL FIX: Fetch VM external IP from GCP metadata for cross-project Swarm
// ============================================================================
async function getVMExternalIP() {
    try {
        const response = await axios.get(
            'http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip',
            { 
                headers: { 'Metadata-Flavor': 'Google' },
                timeout: 3000 
            }
        );
        console.log(`Found VM external IP from GCP metadata: ${response.data}`);
        return response.data;
    } catch (error) {
        console.warn('Could not fetch VM external IP from GCP metadata:', error.message);
        return null;
    }
}

// Get container's IP address on the overlay network (FALLBACK ONLY)
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

// Global variable to store the effective hostname (set during startup)
let EFFECTIVE_HOSTNAME = null;

// Node configuration - NODE_ID should be deterministic
const NODE_ID = process.env.NODE_ID || `storage-node-${uuidv4().slice(0, 8)}`;
const NODE_PORT = process.env.NODE_PORT || 3000;
const NODE_ROLE = process.env.NODE_ROLE || 'STORAGE';

// Use a logical objects folder for fragment objects. This makes addresses
// portable and easier to migrate to object storage later.
const STORAGE_PATH = process.env.STORAGE_PATH || '/data/objects';
const HEARTBEAT_INTERVAL = parseInt(process.env.HEARTBEAT_INTERVAL) || 10000;

async function registerWithMaster(){
    try {
        // Use the effective hostname that was determined at startup
        const apiEndpoint = `http://${EFFECTIVE_HOSTNAME}:${NODE_PORT}`;
        
        console.log(`Registering with master node...`);
        console.log(`API Endpoint: ${apiEndpoint}`);
        console.log(`Node ID: ${NODE_ID}`);
        
        const response = await axios.post(`${MASTER_NODE_URL}/register-node`, {
            nodeId: NODE_ID,
            apiEndpoint: apiEndpoint,
            nodeRole: NODE_ROLE,
            hostname: EFFECTIVE_HOSTNAME
        });
        
        if (response.data.success) {
            console.log(`Storage Node ${NODE_ID} registered with master node.`);
            console.log('Hostname/IP:', EFFECTIVE_HOSTNAME);
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
        hostname: EFFECTIVE_HOSTNAME,
        role: NODE_ROLE,
    });
});

app.post('/fragments', async (req, res) => {
    try {
        const { fragmentId, data, bytes, contentHash } = req.body;
        if (!fragmentId || !data) {
            return res.status(400).json({ error: 'Missing fragmentId or data' });
        }

        // Decide object key – keep it deterministic so we can locate fragments later
        const fileId = req.body.fileId || 'unknown';
        const fragmentOrder = req.body.fragmentOrder !== undefined ? req.body.fragmentOrder : '0';
        const key = path.join(fileId.toString(), `${fragmentOrder}_${fragmentId}.bin`);
        const objectPath = path.join(STORAGE_PATH, key);

        // Ensure parent directory exists
        await fs.mkdir(path.dirname(objectPath), { recursive: true });

        // Store fragment locally as an "object"
        await fs.writeFile(objectPath, Buffer.from(data, 'base64'));

        console.log(`Fragment ${fragmentId} stored at ${objectPath}`);

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
            address: `http://${EFFECTIVE_HOSTNAME}:${NODE_PORT}`,
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
    console.log('Storage Node Starting');
    console.log('=================================');
    
    // ============================================================================
    // CRITICAL: Determine the hostname/IP to use for registration
    // Priority: 1. VM External IP, 2. ENV var, 3. Container IP, 4. Generated ID
    // ============================================================================
    const VM_EXTERNAL_IP = await getVMExternalIP();
    const CONTAINER_IP = getContainerIP();
    const ENV_HOSTNAME = process.env.NODE_HOSTNAME;
    
    // Set the effective hostname (used globally for registration)
    EFFECTIVE_HOSTNAME = VM_EXTERNAL_IP || ENV_HOSTNAME || CONTAINER_IP || `storage-node-${uuidv4().slice(0, 8)}`;
    
    console.log(`Node ID: ${NODE_ID}`);
    console.log(`VM External IP: ${VM_EXTERNAL_IP || 'Not available (not running on GCP VM)'}`);
    console.log(`ENV Hostname: ${ENV_HOSTNAME || 'Not set'}`);
    console.log(`Container IP: ${CONTAINER_IP || 'Not found'}`);
    console.log(`Effective Hostname (for registration): ${EFFECTIVE_HOSTNAME}`);
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
        console.log(`Storage Node server running on ${EFFECTIVE_HOSTNAME}:${NODE_PORT}`);
        console.log(`Connected to Master Node: ${MASTER_NODE_URL}`);
    });
}

startServer().catch((error) => {
    console.error('Error starting node server:', error);
    process.exit(1);
});