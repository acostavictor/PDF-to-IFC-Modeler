// 3D preview of the model, drawn from the meshes the model builder returns. z is up.
import * as THREE from "three";
import { OrbitControls } from "./vendor/three/OrbitControls.js";

export class Viewer {
  constructor(host, onPick) {
    this.host = host;
    this.onPick = onPick;
    this.mode = "material";
    this.selected = null;
    this.centre = new THREE.Vector3();
    this.size = 10;
    this.radius = 10;
    this.fitted = false;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    host.append(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 1e7);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(-30, -40, 25);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.addEventListener("change", () => this.render());
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a949b, 1.5));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(-0.5, -0.8, 1.2);
    this.scene.add(sun);
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.helpers = new THREE.Group();
    this.scene.add(this.helpers);
    new ResizeObserver(() => this.resize()).observe(host);
    this.resize();
    let down = null;
    const el = this.renderer.domElement;
    el.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
    el.addEventListener("pointerup", (e) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
      const r = el.getBoundingClientRect();
      const ray = new THREE.Raycaster();
      ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), this.camera);
      const hit = ray.intersectObjects(this.group.children.filter((o) => o.isMesh), false)[0];
      if (this.onPick) this.onPick(hit ? hit.object.userData.id : null);
    });
  }

  resize() {
    const w = Math.max(this.host.clientWidth, 50), h = Math.max(this.host.clientHeight, 50);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.render();
  }

  render() { this.renderer.render(this.scene, this.camera); }

  clear(group) {
    for (const o of [...group.children]) {
      group.remove(o);
      if (o.geometry) o.geometry.dispose();
      if (o.material) o.material.dispose();
    }
  }

  setMeshes(data) {
    this.clear(this.group);
    this.clear(this.helpers);
    const lo = data.bbox[0], hi = data.bbox[1];
    this.centre.set((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2);
    this.size = Math.max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2], 1);
    this.radius = Math.max(Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2, 0.5);
    const c = this.centre;
    for (const m of data.meshes) {
      const pos = new Float32Array(m.positions.length);
      for (let i = 0; i < pos.length; i += 3) { pos[i] = m.positions[i] - c.x; pos[i + 1] = m.positions[i + 1] - c.y; pos[i + 2] = m.positions[i + 2] - c.z; }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      geo.computeVertexNormals();
      const mat = new THREE.MeshStandardMaterial({ roughness: 0.9, metalness: 0, side: THREE.DoubleSide, transparent: m.opacity < 1, opacity: m.opacity, depthWrite: m.opacity >= 1 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.userData = { id: m.id, rgb: m.rgb, source: m.source_rgb };
      this.group.add(mesh);
      if (m.opacity >= 1) {
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 25), new THREE.LineBasicMaterial({ color: 0x1b2a33, transparent: true, opacity: 0.35 }));
        edges.userData = { edge: true };
        this.group.add(edges);
      }
    }
    // A grid on the datum plane (z = 0) gives a sense of scale and of where the water line is.
    const span = this.size * 1.6, step = Math.pow(10, Math.floor(Math.log10(span / 8)));
    const n = Math.max(2, Math.round(span / step));
    const grid = new THREE.GridHelper(n * step, n, 0x6b8aa0, 0xb9cbd6);
    grid.rotation.x = Math.PI / 2;
    grid.position.set(0, 0, -c.z);
    grid.material.transparent = true; grid.material.opacity = 0.55;
    this.helpers.add(grid);
    const axes = new THREE.AxesHelper(this.size * 0.12);
    axes.position.set(lo[0] - c.x, lo[1] - c.y, -c.z);
    this.helpers.add(axes);
    this.paint();
    if (!this.fitted && data.meshes.length) { this.fit(); this.fitted = true; }
    this.render();
  }

  paint() {
    for (const o of this.group.children) {
      if (!o.isMesh) continue;
      const rgb = this.mode === "source" ? o.userData.source : o.userData.rgb;
      o.material.color.setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace);
      o.material.emissive.setHex(o.userData.id === this.selected ? 0xc8641a : 0x000000);
      o.material.emissiveIntensity = o.userData.id === this.selected ? 0.55 : 0;
    }
    this.render();
  }

  setMode(mode) { this.mode = mode; this.paint(); }
  select(id) { this.selected = id; this.paint(); }

  fit() {
    // Far enough back that the whole bounding sphere is inside the narrower of the two view angles.
    const half = (this.camera.fov / 2) * Math.PI / 180;
    const d = (this.radius || this.size) / Math.sin(Math.min(half, Math.atan(Math.tan(half) * this.camera.aspect))) * 1.05;
    const dir = new THREE.Vector3(-0.75, -0.95, 0.6).normalize();
    this.controls.target.set(0, 0, 0);
    this.camera.position.copy(dir.multiplyScalar(d));
    this.camera.near = d / 500; this.camera.far = d * 40;
    this.camera.updateProjectionMatrix();
    this.controls.update();
    this.render();
  }

  reset() { this.fitted = false; }
}
