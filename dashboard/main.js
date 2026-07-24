// dashboard/main.js
const diagnosticsText = document.getElementById("diagnostics-text");

// -- Three.js 3D Setup --
const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x0b0f19, 0.02);

const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 1000);
camera.position.set(0, 15, 20);
camera.lookAt(0, 0, 0);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setSize(window.innerWidth, window.innerHeight);
document.body.appendChild(renderer.domElement);

// Lighting
const ambientLight = new THREE.AmbientLight(0xffffff, 0.3);
scene.add(ambientLight);
const directionalLight = new THREE.DirectionalLight(0x4fc1ff, 0.8);
directionalLight.position.set(10, 20, 10);
scene.add(directionalLight);

// -- The "Double-Decker" Visuals --
// Ground Floor (Plane)
const groundGeo = new THREE.PlaneGeometry(20, 20);
const groundMat = new THREE.MeshBasicMaterial({ color: 0x111122, transparent: true, opacity: 0.8, side: THREE.DoubleSide });
const ground = new THREE.Mesh(groundGeo, groundMat);
ground.rotation.x = Math.PI / 2;
scene.add(ground);

// Grid Helpers
const groundGrid = new THREE.GridHelper(20, 20, 0x4fc1ff, 0x223344);
scene.add(groundGrid);

// Roof Security Plan (Floating Floor)
const roofGeo = new THREE.PlaneGeometry(20, 20);
const roofMat = new THREE.MeshBasicMaterial({ color: 0x221122, transparent: true, opacity: 0.4, side: THREE.DoubleSide });
const roof = new THREE.Mesh(roofGeo, roofMat);
roof.rotation.x = Math.PI / 2;
roof.position.y = 5; // Floating above
scene.add(roof);

const roofGrid = new THREE.GridHelper(20, 20, 0xff4f4f, 0x442222);
roofGrid.position.y = 5;
scene.add(roofGrid);

// Dome Visual Representation (Sphere)
const domeGeo = new THREE.SphereGeometry(12, 32, 16, 0, Math.PI * 2, 0, Math.PI / 2);
const domeMat = new THREE.MeshBasicMaterial({ color: 0x4fc1ff, wireframe: true, transparent: true, opacity: 0.1 });
const dome = new THREE.Mesh(domeGeo, domeMat);
scene.add(dome);

// Target Markers Dictionary
const targetMarkers = {};

function createMarker(color) {
    const geo = new THREE.CylinderGeometry(0.5, 0.5, 0.1, 16);
    const mat = new THREE.MeshBasicMaterial({ color: color });
    const mesh = new THREE.Mesh(geo, mat);
    return mesh;
}

// -- Animation Loop --
function animate() {
    requestAnimationFrame(animate);
    dome.rotation.y += 0.001; // Slow spin for effect
    renderer.render(scene, camera);
}
animate();

// Handle Window Resize
window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
});


// -- Telemetry WebSockets Integration --
const wsPorts = [8766, 8765];
let socket = null;

function connectWebSocket(index = 0) {
    if (index >= wsPorts.length) {
        diagnosticsText.innerHTML = "<span class='danger'>SYSTEM OFFLINE</span>";
        return;
    }

    const port = wsPorts[index];
    socket = new WebSocket(`ws://localhost:${port}`);

    socket.onopen = () => {
        console.log(`[CONNECTED] Invisible Dome Active on :${port}`);
        diagnosticsText.innerHTML = "<span class='secure'>SYSTEM ONLINE</span>";
    };

    socket.onmessage = (event) => {
        const msg = JSON.parse(event.data);

        if (msg.protocol !== "invisible4eyes.telemetry") return;

        if (msg.type === "diagnostics_snapshot") {
            updateTextDiagnostics(msg.payload);
        } else if (msg.type === "tracking_update") {
            updateVisualTargets(msg.payload.targets);
        }
    };

    socket.onerror = () => {
        socket.close();
    };

    socket.onclose = () => {
        connectWebSocket(index + 1);
    };
}

connectWebSocket();


function updateTextDiagnostics(data) {
    let activeNodes = 0;
    for (const meta of Object.values(data.nodes)) {
        if (meta.connected) activeNodes++;
    }

    const zoneLines = Object.entries(data.ambient_zones || {})
        .map(([zoneName, zone]) => `${zoneName}: ${(zone.rf_pressure || 0).toFixed(3)} (${zone.packet_count || 0} pkt)`)
        .join('<br/>');
    
    const isSafe = activeNodes === 4;
    const statusClass = isSafe ? "secure" : "danger";
    
    diagnosticsText.innerHTML = `
        Status: <strong class="${statusClass}">${activeNodes}/4 Eyes Active</strong><br/>
        Queue: ${data.pipeline.queue_depth}<br/>
        Health: ${isSafe ? 'Secure' : 'Degraded'}<br/>
        Load: ${data.host.cpu_utilization}%<br/>
        Zones:<br/>${zoneLines || 'Awaiting zone data...'}
    `;
}

function updateVisualTargets(targets) {
    // 1. Mark existing targets as stale
    Object.values(targetMarkers).forEach(m => m.userData.updated = false);
    
    // 2. Update or create targets
    targets.forEach(t => {
        let isRoof = t.position[1] > 2.5; // Threshold for determining floor 
        let yPos = isRoof ? 5 : 0;        // Snap to roof or ground plane
        let color = isRoof ? 0xff4444 : 0x44ff44; // Red for Roof, Green for Ground
        
        let marker = targetMarkers[t.id];
        if (!marker) {
            marker = createMarker(color);
            scene.add(marker);
            targetMarkers[t.id] = marker;
        }
        
        // Convert normalized coordinates to grid space (Assuming spatial coords are (-10, 10))
        // This math will need tuning based on actual tracker outputs
        let gridX = t.position[0] * 10; 
        let gridZ = t.position[2] * 10;
        
        marker.position.set(gridX, yPos, gridZ);
        marker.material.color.setHex(color); // Update color dynamically if they "change floors"
        marker.userData.updated = true;
        
        // Map confidence to opacity
        marker.material.opacity = Math.max(0.2, t.confidence);
        marker.material.transparent = true;
    });
    
    // 3. Remove stale targets
    Object.keys(targetMarkers).forEach(id => {
        if (!targetMarkers[id].userData.updated) {
            scene.remove(targetMarkers[id]);
            delete targetMarkers[id];
        }
    });
}