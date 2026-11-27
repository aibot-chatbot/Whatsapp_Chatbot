import type * as THREE from "three";

type ThreeModule = typeof import("./three-subset");
type ThemeMode = "dark" | "light";
type Vec3Tuple = readonly [number, number, number];

interface NavigatorWithConnection extends Navigator {
  readonly connection?: { readonly saveData?: boolean };
}

interface WindowWithIdle {
  requestIdleCallback?: (cb: () => void, opts?: { timeout?: number }) => number;
  cancelIdleCallback?: (handle: number) => void;
}

interface GsapTweenLike {
  progress(value: number): unknown;
}

interface GsapScrollTriggerLike {
  readonly progress?: number;
  getTween?: () => GsapTweenLike | undefined;
  kill(): void;
}

interface GsapTimelineLike {
  to(target: object, vars: Record<string, unknown>, position?: number | string): GsapTimelineLike;
  progress(value: number): GsapTimelineLike;
  kill(): void;
  scrollTrigger?: GsapScrollTriggerLike;
}

interface WindowWithGsap extends Window {
  gsap?: {
    registerPlugin(...plugins: unknown[]): void;
    timeline(vars?: Record<string, unknown>): GsapTimelineLike;
  };
  ScrollTrigger?: { refresh(): void };
}

interface ThemePalette {
  readonly blending: THREE.Blending;
  readonly coreInner: number;
  readonly coreRim: number;
  readonly wirePrimary: number;
  readonly wireSecondary: number;
  readonly halo: number;
  readonly whatsapp: number;
  readonly telegram: number;
  readonly webchat: number;
  readonly docFill: number;
  readonly docLine: number;
  readonly docAccent: number;
  readonly networkLine: number;
  readonly networkNode: number;
  readonly networkPulse: number;
  readonly stars: number;
  readonly alpha: {
    readonly core: number;
    readonly wire: number;
    readonly wireOuter: number;
    readonly halo: number;
    readonly streamDot: number;
    readonly streamLine: number;
    readonly doc: number;
    readonly netLine: number;
    readonly netNode: number;
    readonly netPulse: number;
    readonly stars: number;
  };
}

interface StoryState {
  camX: number;
  camY: number;
  camZ: number;
  lookX: number;
  lookY: number;
  coreOffsetX: number;
  coreScale: number;
  coreOpacity: number;
  corePulse: number;
  haloOpacity: number;
  streamsOpacity: number;
  docsOpacity: number;
  docsFlow: number;
  networkOpacity: number;
  networkPulse: number;
  starfieldOpacity: number;
}

interface DisposablePool {
  trackGeo<T extends THREE.BufferGeometry>(geo: T): T;
  trackMat<T extends THREE.Material>(mat: T): T;
  disposeAll(): void;
}

interface SceneActor {
  readonly group: THREE.Group;
  applyTheme(palette: ThemePalette): void;
  setPixelRatio(dpr: number): void;
  update(elapsed: number, state: StoryState, palette: ThemePalette): void;
}

const SMALL_VIEWPORT_WIDTH = 768;

const createPalettes = (T: ThreeModule): Record<ThemeMode, ThemePalette> => ({
  dark: {
    blending: T.AdditiveBlending,
    coreInner: 0x082238, coreRim: 0x22d3ee, wirePrimary: 0x22d3ee, wireSecondary: 0x38bdf8,
    halo: 0x38bdf8, whatsapp: 0x25d366, telegram: 0x229ed9, webchat: 0x22d3ee,
    docFill: 0x0e2a40, docLine: 0x94a3b8, docAccent: 0x22d3ee,
    networkLine: 0x22d3ee, networkNode: 0x38bdf8, networkPulse: 0x7dd3fc, stars: 0x94a3b8,
    alpha: {
      core: 0.56, wire: 0.34, wireOuter: 0.15, halo: 0.46, streamDot: 0.78, streamLine: 0.18,
      doc: 0.52, netLine: 0.25, netNode: 0.6, netPulse: 0.85, stars: 0.42,
    },
  },
  // Warm-paper light mode uses NormalBlending because additive light washes out on #F6F5F1.
  light: {
    blending: T.NormalBlending,
    coreInner: 0xcbe6ec, coreRim: 0x0e7490, wirePrimary: 0x0e7490, wireSecondary: 0x0b6478,
    halo: 0x0e7490, whatsapp: 0x16a34a, telegram: 0x0284c7, webchat: 0x0e7490,
    docFill: 0xe8f1f3, docLine: 0x58574f, docAccent: 0x0e7490,
    networkLine: 0x0b6478, networkNode: 0x0e7490, networkPulse: 0x0284c7, stars: 0x58574f,
    alpha: {
      core: 0.34, wire: 0.25, wireOuter: 0.12, halo: 0.32, streamDot: 0.58, streamLine: 0.15,
      doc: 0.4, netLine: 0.2, netNode: 0.45, netPulse: 0.68, stars: 0.24,
    },
  },
});

const SOFT_DOT_FRAG = /* glsl */ `
uniform vec3 uColor;
varying float vAlpha;
void main() {
  float d = length(gl_PointCoord - vec2(0.5));
  if (d > 0.5) discard;
  float f = smoothstep(0.5, 0.05, d);
  float a = f * f * vAlpha;
  if (a < 0.004) discard;
  gl_FragColor = vec4(uColor, clamp(a, 0.0, 0.95));
}`;

const FRESNEL_VERT = /* glsl */ `
uniform float uTime;
uniform float uPulse;
varying vec3 vNormalView;
varying vec3 vViewPos;
void main() {
  float w = sin(position.x * 2.4 + uTime * 0.9) * cos(position.y * 2.1 - uTime * 0.7) * sin(position.z * 2.3 + uTime * 0.6);
  vec4 mvPos = modelViewMatrix * vec4(position + normal * (w * (0.02 + uPulse * 0.018)), 1.0);
  vNormalView = normalize(normalMatrix * normal);
  vViewPos = -mvPos.xyz;
  gl_Position = projectionMatrix * mvPos;
}`;

const FRESNEL_FRAG = /* glsl */ `
uniform vec3 uCoreColor;
uniform vec3 uRimColor;
uniform float uOpacity;
uniform float uPulse;
varying vec3 vNormalView;
varying vec3 vViewPos;
void main() {
  float ndotv = clamp(abs(dot(normalize(vNormalView), normalize(vViewPos))), 0.0, 1.0);
  float fresnel = pow(1.0 - ndotv, 2.35);
  vec3 col = mix(uCoreColor, uRimColor, clamp(fresnel * 1.15 + uPulse * 0.2, 0.0, 1.0));
  float a = (fresnel * (0.72 + uPulse * 0.22) + pow(ndotv, 1.6) * 0.2) * uOpacity;
  if (a < 0.004) discard;
  gl_FragColor = vec4(col, clamp(a, 0.0, 0.9));
}`;

const VERTEX_DOT_VERT = /* glsl */ `
attribute float aSize;
uniform float uPixelRatio;
uniform float uOpacity;
varying float vAlpha;
void main() {
  vec4 mvPos = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mvPos;
  gl_PointSize = clamp(aSize * uPixelRatio * (18.0 / max(-mvPos.z, 1.0)), 1.5, 16.0);
  vAlpha = uOpacity;
}`;

const HALO_VERT = /* glsl */ `
attribute float aAngle;
attribute float aRadius;
attribute float aHeight;
attribute float aSpeed;
attribute float aSize;
attribute float aPhase;
uniform float uTime;
uniform float uPixelRatio;
uniform float uOpacity;
varying float vAlpha;
void main() {
  float theta = aAngle + uTime * aSpeed;
  vec3 pos = vec3(cos(theta) * aRadius, aHeight + sin(uTime * 0.55 + aPhase) * 0.16, sin(theta) * aRadius);
  vec4 mvPos = modelViewMatrix * vec4(pos, 1.0);
  gl_Position = projectionMatrix * mvPos;
  gl_PointSize = clamp(aSize * uPixelRatio * (18.0 / max(-mvPos.z, 1.0)), 1.5, 18.0);
  vAlpha = uOpacity * (0.65 + 0.35 * sin(uTime * 1.1 + aPhase * 3.0));
}`;

const STREAM_VERT = /* glsl */ `
attribute float aOffset;
attribute float aSpeed;
attribute float aSize;
attribute vec3 aSpread;
uniform float uTime;
uniform float uPixelRatio;
uniform float uOpacity;
uniform vec3 uP0;
uniform vec3 uP1;
uniform vec3 uP2;
uniform vec3 uP3;
varying float vAlpha;
void main() {
  float t = fract(aOffset + uTime * aSpeed);
  float inv = 1.0 - t;
  vec3 pos = (inv * inv * inv) * uP0 + (3.0 * inv * inv * t) * uP1
           + (3.0 * inv * t * t) * uP2 + (t * t * t) * uP3;
  pos += aSpread * (1.0 - smoothstep(0.52, 0.98, t));
  vec4 mvPos = modelViewMatrix * vec4(pos, 1.0);
  gl_Position = projectionMatrix * mvPos;
  gl_PointSize = clamp(aSize * (1.0 + 0.35 * smoothstep(0.65, 0.95, t)) * uPixelRatio * (20.0 / max(-mvPos.z, 1.0)), 1.5, 20.0);
  vAlpha = uOpacity * smoothstep(0.0, 0.14, t) * (1.0 - smoothstep(0.88, 1.0, t));
}`;

const DOC_CARD_VERT = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const DOC_CARD_FRAG = /* glsl */ `
uniform vec3 uFillColor;
uniform vec3 uLineColor;
uniform vec3 uAccentColor;
uniform float uOpacity;
varying vec2 vUv;
float docLine(vec2 uv, float y, float endX) {
  return (1.0 - smoothstep(0.011, 0.022, abs(uv.y - y))) * step(0.14, uv.x) * step(uv.x, endX);
}
void main() {
  vec2 edge = min(vUv, 1.0 - vUv);
  float border = 1.0 - smoothstep(0.022, 0.048, min(edge.x, edge.y));
  float header = step(0.14, vUv.x) * step(vUv.x, 0.56) * step(0.79, vUv.y) * step(vUv.y, 0.855);
  float lines = max(docLine(vUv, 0.67, 0.86), docLine(vUv, 0.555, 0.78));
  lines = max(lines, max(docLine(vUv, 0.44, 0.84), docLine(vUv, 0.325, 0.68)));
  lines = max(lines, docLine(vUv, 0.21, 0.56));
  vec3 col = mix(mix(uFillColor, uLineColor, clamp(border * 0.9 + lines * 0.75, 0.0, 1.0)), uAccentColor, header);
  float a = clamp(0.14 + border * 0.52 + lines * 0.34 + header * 0.55, 0.0, 0.85) * uOpacity;
  if (a < 0.004) discard;
  gl_FragColor = vec4(col, a);
}`;

const PULSE_VERT = /* glsl */ `
attribute vec3 aMid;
attribute vec3 aEnd;
attribute float aOffset;
attribute float aSpeed;
attribute float aSize;
uniform float uTime;
uniform float uPixelRatio;
uniform float uOpacity;
varying float vAlpha;
void main() {
  float t = fract(aOffset + uTime * aSpeed);
  vec4 mvPos = modelViewMatrix * vec4((2.0 * (1.0 - t) * t) * aMid + (t * t) * aEnd, 1.0);
  gl_Position = projectionMatrix * mvPos;
  gl_PointSize = clamp(aSize * uPixelRatio * (22.0 / max(-mvPos.z, 1.0)), 2.0, 22.0);
  vAlpha = uOpacity * smoothstep(0.0, 0.12, t) * (1.0 - smoothstep(0.9, 1.0, t));
}`;

const STAR_VERT = /* glsl */ `
attribute float aSize;
attribute float aPhase;
uniform float uTime;
uniform float uPixelRatio;
uniform float uOpacity;
varying float vAlpha;
void main() {
  vec4 mvPos = modelViewMatrix * vec4(position.x, position.y + sin(uTime * 0.18 + aPhase) * 0.14, position.z, 1.0);
  gl_Position = projectionMatrix * mvPos;
  gl_PointSize = clamp(aSize * uPixelRatio * (26.0 / max(-mvPos.z, 1.0)), 1.2, 12.0);
  vAlpha = uOpacity * (0.58 + 0.42 * sin(uTime * 0.65 + aPhase * 2.7));
}`;

function createDisposablePool(): DisposablePool {
  const geometries: THREE.BufferGeometry[] = [];
  const materials: THREE.Material[] = [];
  return {
    trackGeo<T extends THREE.BufferGeometry>(geo: T): T { geometries.push(geo); return geo; },
    trackMat<T extends THREE.Material>(mat: T): T { materials.push(mat); return mat; },
    disposeAll(): void {
      for (const g of geometries) g.dispose();
      for (const m of materials) m.dispose();
      geometries.length = 0;
      materials.length = 0;
    },
  };
}

// Deterministic PRNG keeps particle placement identical across loads and visual checks.
function createSeededRandom(seed: number): () => number {
  let s = seed >>> 0;
  return (): number => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const clamp = (v: number, min: number, max: number): number => Math.max(min, Math.min(max, v));
const readTheme = (): ThemeMode => (document.documentElement.dataset.theme === "light" ? "light" : "dark");
const isSmallScreen = (): boolean => window.innerWidth < SMALL_VIEWPORT_WIDTH;
const getCappedPixelRatio = (): number => Math.min(window.devicePixelRatio || 1, isSmallScreen() ? 1 : 1.5);

function shouldSkipScene(): boolean {
  if (typeof window === "undefined") return true;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return true;
  return Boolean((navigator as NavigatorWithConnection).connection?.saveData);
}

function isWebGLAvailable(): boolean {
  try {
    const probe = document.createElement("canvas");
    const gl = probe.getContext("webgl2");
    if (!gl) return false;
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    return true;
  } catch {
    return false;
  }
}

function createInitialStoryState(): StoryState {
  return {
    camX: 0, camY: 0.15, camZ: 7.2, lookX: 0, lookY: 0,
    coreOffsetX: isSmallScreen() ? 0 : 1.25,
    coreScale: 1, coreOpacity: 1, corePulse: 0.25, haloOpacity: 0.85,
    streamsOpacity: 0, docsOpacity: 0, docsFlow: 0,
    networkOpacity: 0, networkPulse: 0, starfieldOpacity: 0.28,
  };
}

function setBlending(mat: THREE.Material, blending: THREE.Blending): void {
  if (mat.blending !== blending) {
    mat.blending = blending;
    mat.needsUpdate = true;
  }
}

function makeLineMat(
  T: ThreeModule, pool: DisposablePool, color: number, opacity: number, blending: THREE.Blending,
): THREE.LineBasicMaterial {
  return pool.trackMat(new T.LineBasicMaterial({ color, transparent: true, opacity, depthWrite: false, blending }));
}

function makeShaderMat(
  T: ThreeModule,
  pool: DisposablePool,
  uniforms: Record<string, THREE.IUniform>,
  vertexShader: string,
  fragmentShader: string,
  blending: THREE.Blending,
  side?: THREE.Side,
): THREE.ShaderMaterial {
  return pool.trackMat(new T.ShaderMaterial({
    uniforms, vertexShader, fragmentShader, transparent: true, depthWrite: false, blending,
    ...(side !== undefined ? { side } : {}),
  }));
}

function buildCore(
  T: ThreeModule, pool: DisposablePool, small: boolean, rand: () => number, dpr: number, palette: ThemePalette,
): SceneActor {
  const group = new T.Group();
  const pivot = new T.Group();
  group.add(pivot);

  const fresnel = {
    uTime: { value: 0 }, uPulse: { value: 0.25 }, uOpacity: { value: palette.alpha.core },
    uCoreColor: { value: new T.Color(palette.coreInner) }, uRimColor: { value: new T.Color(palette.coreRim) },
  };
  const sphereMat = makeShaderMat(T, pool, { ...fresnel }, FRESNEL_VERT, FRESNEL_FRAG, palette.blending);
  pivot.add(new T.Mesh(pool.trackGeo(new T.SphereGeometry(1.16, 36, 28)), sphereMat));

  const innerBase = new T.IcosahedronGeometry(1.62, 1);
  const innerWireMat = makeLineMat(T, pool, palette.wirePrimary, palette.alpha.wire, palette.blending);
  pivot.add(new T.LineSegments(pool.trackGeo(new T.EdgesGeometry(innerBase)), innerWireMat));

  // Deduplicate shared icosahedron corners so vertex highlights do not over-brighten.
  const posAttr = innerBase.getAttribute("position");
  const seen = new Set<string>();
  const uniqueVerts: number[] = [];
  for (let i = 0; i < posAttr.count; i++) {
    const x = posAttr.getX(i), y = posAttr.getY(i), z = posAttr.getZ(i);
    const key = `${Math.round(x * 100)},${Math.round(y * 100)},${Math.round(z * 100)}`;
    if (!seen.has(key)) { seen.add(key); uniqueVerts.push(x, y, z); }
  }
  innerBase.dispose();

  const vertGeo = pool.trackGeo(new T.BufferGeometry());
  vertGeo.setAttribute("position", new T.Float32BufferAttribute(uniqueVerts, 3));
  vertGeo.setAttribute("aSize", new T.Float32BufferAttribute(new Float32Array(uniqueVerts.length / 3).fill(2.4), 1));
  const vertUniforms = {
    uPixelRatio: { value: dpr }, uOpacity: { value: palette.alpha.wire * 1.3 },
    uColor: { value: new T.Color(palette.wirePrimary) },
  };
  const vertMat = makeShaderMat(T, pool, { ...vertUniforms }, VERTEX_DOT_VERT, SOFT_DOT_FRAG, palette.blending);
  pivot.add(new T.Points(vertGeo, vertMat));

  const outerBase = new T.IcosahedronGeometry(1.98, 0);
  const outerWireMat = makeLineMat(T, pool, palette.wireSecondary, palette.alpha.wireOuter, palette.blending);
  const outerWire = new T.LineSegments(pool.trackGeo(new T.EdgesGeometry(outerBase)), outerWireMat);
  outerBase.dispose();
  pivot.add(outerWire);

  const haloCount = small ? 95 : 220;
  const hPos = new Float32Array(haloCount * 3);
  const hAngle = new Float32Array(haloCount);
  const hRadius = new Float32Array(haloCount);
  const hHeight = new Float32Array(haloCount);
  const hSpeed = new Float32Array(haloCount);
  const hSize = new Float32Array(haloCount);
  const hPhase = new Float32Array(haloCount);
  for (let i = 0; i < haloCount; i++) {
    const a = rand() * Math.PI * 2, r = 2.25 + rand() * 1.75, h = (rand() - 0.5) * 1.45;
    hAngle[i] = a; hRadius[i] = r; hHeight[i] = h;
    hSpeed[i] = 0.08 + rand() * 0.14; hSize[i] = 1.6 + rand() * 2.2; hPhase[i] = rand() * Math.PI * 2;
    hPos[i * 3] = Math.cos(a) * r; hPos[i * 3 + 1] = h; hPos[i * 3 + 2] = Math.sin(a) * r;
  }
  const haloGeo = pool.trackGeo(new T.BufferGeometry());
  haloGeo.setAttribute("position", new T.Float32BufferAttribute(hPos, 3));
  haloGeo.setAttribute("aAngle", new T.Float32BufferAttribute(hAngle, 1));
  haloGeo.setAttribute("aRadius", new T.Float32BufferAttribute(hRadius, 1));
  haloGeo.setAttribute("aHeight", new T.Float32BufferAttribute(hHeight, 1));
  haloGeo.setAttribute("aSpeed", new T.Float32BufferAttribute(hSpeed, 1));
  haloGeo.setAttribute("aSize", new T.Float32BufferAttribute(hSize, 1));
  haloGeo.setAttribute("aPhase", new T.Float32BufferAttribute(hPhase, 1));

  const haloUniforms = {
    uTime: { value: 0 }, uPixelRatio: { value: dpr }, uOpacity: { value: palette.alpha.halo },
    uColor: { value: new T.Color(palette.halo) },
  };
  const haloMat = makeShaderMat(T, pool, { ...haloUniforms }, HALO_VERT, SOFT_DOT_FRAG, palette.blending);
  const halo = new T.Points(haloGeo, haloMat);
  halo.frustumCulled = false;
  halo.rotation.set(0.32, 0, -0.18);
  group.add(halo);

  const allMats: THREE.Material[] = [sphereMat, innerWireMat, outerWireMat, vertMat, haloMat];
  return {
    group,
    applyTheme(next: ThemePalette): void {
      fresnel.uCoreColor.value.setHex(next.coreInner);
      fresnel.uRimColor.value.setHex(next.coreRim);
      innerWireMat.color.setHex(next.wirePrimary);
      outerWireMat.color.setHex(next.wireSecondary);
      vertUniforms.uColor.value.setHex(next.wirePrimary);
      haloUniforms.uColor.value.setHex(next.halo);
      for (const m of allMats) setBlending(m, next.blending);
    },
    setPixelRatio(nextDpr: number): void {
      vertUniforms.uPixelRatio.value = nextDpr;
      haloUniforms.uPixelRatio.value = nextDpr;
    },
    update(elapsed: number, state: StoryState, active: ThemePalette): void {
      group.position.x = state.coreOffsetX;
      group.scale.setScalar(state.coreScale);
      pivot.rotation.set(Math.sin(elapsed * 0.22) * 0.14, elapsed * 0.16, 0);
      outerWire.rotation.set(0, -elapsed * 0.26, elapsed * 0.09);

      fresnel.uTime.value = elapsed;
      fresnel.uPulse.value = state.corePulse;
      fresnel.uOpacity.value = active.alpha.core * state.coreOpacity;
      innerWireMat.opacity = active.alpha.wire * state.coreOpacity;
      outerWireMat.opacity = active.alpha.wireOuter * state.coreOpacity;
      vertUniforms.uOpacity.value = active.alpha.wire * 1.35 * state.coreOpacity;
      haloUniforms.uTime.value = elapsed;
      haloUniforms.uOpacity.value = active.alpha.halo * state.haloOpacity;
      halo.visible = haloUniforms.uOpacity.value > 0.005;
    },
  };
}

interface StreamDef {
  readonly colorKey: "whatsapp" | "telegram" | "webchat";
  readonly points: readonly [Vec3Tuple, Vec3Tuple, Vec3Tuple, Vec3Tuple];
}

const STREAM_DEFS: readonly StreamDef[] = [
  { colorKey: "whatsapp", points: [[-8.4, 3.0, -1.6], [-4.6, 2.3, 1.0], [-2.1, 0.75, 0.45], [0, 0, 0]] },
  { colorKey: "telegram", points: [[8.4, 2.3, -1.4], [4.5, 1.5, 1.2], [1.95, 0.45, 0.4], [0, 0, 0]] },
  { colorKey: "webchat", points: [[-6.8, -3.5, -0.9], [-3.1, -2.35, 1.35], [-1.25, -0.8, 0.55], [0, 0, 0]] },
];

function buildStreams(
  T: ThreeModule, pool: DisposablePool, small: boolean, rand: () => number, dpr: number, palette: ThemePalette,
): SceneActor {
  const group = new T.Group();
  const count = small ? 34 : 72;
  const toVec = (pt: Vec3Tuple): THREE.Vector3 => new T.Vector3(pt[0], pt[1], pt[2]);

  const entries = STREAM_DEFS.map((def) => {
    const p0 = toVec(def.points[0]), p1 = toVec(def.points[1]);
    const p2 = toVec(def.points[2]), p3 = toVec(def.points[3]);
    const curve = new T.CubicBezierCurve3(p0, p1, p2, p3);
    const guideMat = makeLineMat(T, pool, palette[def.colorKey], 0, palette.blending);
    group.add(new T.Line(pool.trackGeo(new T.BufferGeometry().setFromPoints(curve.getPoints(42))), guideMat));

    const offsets = new Float32Array(count);
    const speeds = new Float32Array(count);
    const sizes = new Float32Array(count);
    const spreads = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      offsets[i] = i / count + rand() * 0.04;
      speeds[i] = 0.14 + rand() * 0.09;
      sizes[i] = 2.0 + rand() * 2.4;
      spreads[i * 3] = (rand() - 0.5) * 0.46;
      spreads[i * 3 + 1] = (rand() - 0.5) * 0.46;
      spreads[i * 3 + 2] = (rand() - 0.5) * 0.46;
    }

    const dotGeo = pool.trackGeo(new T.BufferGeometry());
    dotGeo.setAttribute("position", new T.Float32BufferAttribute(new Float32Array(count * 3), 3));
    dotGeo.setAttribute("aOffset", new T.Float32BufferAttribute(offsets, 1));
    dotGeo.setAttribute("aSpeed", new T.Float32BufferAttribute(speeds, 1));
    dotGeo.setAttribute("aSize", new T.Float32BufferAttribute(sizes, 1));
    dotGeo.setAttribute("aSpread", new T.Float32BufferAttribute(spreads, 3));

    const uniforms = {
      uTime: { value: 0 }, uPixelRatio: { value: dpr }, uOpacity: { value: 0 },
      uP0: { value: p0 }, uP1: { value: p1 }, uP2: { value: p2 }, uP3: { value: p3 },
      uColor: { value: new T.Color(palette[def.colorKey]) },
    };
    const dotMat = makeShaderMat(T, pool, { ...uniforms }, STREAM_VERT, SOFT_DOT_FRAG, palette.blending);
    const points = new T.Points(dotGeo, dotMat);
    points.frustumCulled = false;
    group.add(points);
    return { colorKey: def.colorKey, guideMat, dotMat, uniforms };
  });

  group.visible = false;
  return {
    group,
    applyTheme(next: ThemePalette): void {
      for (const e of entries) {
        e.guideMat.color.setHex(next[e.colorKey]);
        e.uniforms.uColor.value.setHex(next[e.colorKey]);
        setBlending(e.guideMat, next.blending);
        setBlending(e.dotMat, next.blending);
      }
    },
    setPixelRatio(nextDpr: number): void {
      for (const e of entries) e.uniforms.uPixelRatio.value = nextDpr;
    },
    update(elapsed: number, state: StoryState, active: ThemePalette): void {
      group.visible = state.streamsOpacity > 0.005;
      if (!group.visible) return;
      group.position.x = state.coreOffsetX;
      for (const e of entries) {
        e.uniforms.uTime.value = elapsed;
        e.uniforms.uOpacity.value = active.alpha.streamDot * state.streamsOpacity;
        e.guideMat.opacity = active.alpha.streamLine * state.streamsOpacity;
      }
    },
  };
}

function buildDocuments(
  T: ThreeModule, pool: DisposablePool, small: boolean, rand: () => number, palette: ThemePalette,
): SceneActor {
  const group = new T.Group();
  const count = small ? 7 : 12;
  const planeGeo = pool.trackGeo(new T.PlaneGeometry(0.76, 1.02));

  const cards = Array.from({ length: count }, (_, i) => {
    const uniforms = {
      uFillColor: { value: new T.Color(palette.docFill) },
      uLineColor: { value: new T.Color(palette.docLine) },
      uAccentColor: { value: new T.Color(palette.docAccent) },
      uOpacity: { value: 0 },
    };
    const mat = makeShaderMat(T, pool, { ...uniforms }, DOC_CARD_VERT, DOC_CARD_FRAG, palette.blending, T.DoubleSide);
    const mesh = new T.Mesh(planeGeo, mat);
    group.add(mesh);
    return {
      mesh, mat, uniforms,
      baseAngle: (i / count) * Math.PI * 2 + (rand() - 0.5) * 0.35,
      outerRadius: 4.5 + rand() * 1.9,
      yOffset: (rand() - 0.5) * 2.5,
      phase: i / count,
      speed: 0.085 + rand() * 0.035,
      tiltX: (rand() - 0.5) * 0.45,
      tiltZ: (rand() - 0.5) * 0.35,
    };
  });

  group.visible = false;
  return {
    group,
    applyTheme(next: ThemePalette): void {
      for (const c of cards) {
        c.uniforms.uFillColor.value.setHex(next.docFill);
        c.uniforms.uLineColor.value.setHex(next.docLine);
        c.uniforms.uAccentColor.value.setHex(next.docAccent);
        setBlending(c.mat, next.blending);
      }
    },
    setPixelRatio(): void {},
    update(elapsed: number, state: StoryState, active: ThemePalette): void {
      group.visible = state.docsOpacity > 0.005;
      if (!group.visible) return;
      group.position.x = state.coreOffsetX;
      for (const c of cards) {
        const cycle = (c.phase + elapsed * c.speed + state.docsFlow * 0.45) % 1;
        const r = c.outerRadius * (1 - cycle * 0.72) + 1.15 * cycle;
        const a = c.baseAngle + cycle * 1.15 + elapsed * 0.08;
        const y = c.yOffset * (1 - cycle * 0.85) + Math.sin(elapsed * 0.7 + c.baseAngle) * 0.14;
        c.mesh.position.set(Math.cos(a) * r, y, Math.sin(a) * r * 0.75);
        c.mesh.rotation.set(c.tiltX + Math.sin(elapsed * 0.5 + c.baseAngle) * 0.12, -a + Math.PI * 0.5, c.tiltZ);
        c.mesh.scale.setScalar(0.72 + (1 - cycle) * 0.38);
        c.uniforms.uOpacity.value = active.alpha.doc * state.docsOpacity
          * clamp(cycle / 0.16, 0, 1) * clamp((1 - cycle) / 0.22, 0, 1);
      }
    },
  };
}

function buildNetwork(
  T: ThreeModule, pool: DisposablePool, small: boolean, rand: () => number, dpr: number, palette: ThemePalette,
): SceneActor {
  const group = new T.Group();
  const nodeCount = 6;
  const ringRadius = small ? 2.75 : 3.45;
  const octGeo = pool.trackGeo(new T.OctahedronGeometry(0.18, 0));

  const ringPts = Array.from({ length: 24 }, (_, i) => {
    const theta = (i / 24) * Math.PI * 2;
    return new T.Vector3(Math.cos(theta) * 0.3, Math.sin(theta) * 0.3, 0);
  });
  const nodeRingGeo = pool.trackGeo(new T.BufferGeometry().setFromPoints(ringPts));

  const spokeMat = makeLineMat(T, pool, palette.networkLine, 0, palette.blending);
  const perimeterMat = makeLineMat(T, pool, palette.networkLine, 0, palette.blending);
  const nodeHaloMat = makeLineMat(T, pool, palette.networkLine, 0, palette.blending);
  const nodeMat = pool.trackMat(new T.MeshBasicMaterial({
    color: palette.networkNode, transparent: true, opacity: 0, depthWrite: false, blending: palette.blending,
  }));

  const nodePositions: THREE.Vector3[] = [];
  const midPositions: THREE.Vector3[] = [];
  const nodeGroups: THREE.Group[] = [];

  for (let i = 0; i < nodeCount; i++) {
    const a = (i / nodeCount) * Math.PI * 2 + Math.PI / 6;
    const pos = new T.Vector3(Math.cos(a) * ringRadius, Math.sin(a * 2) * 0.65, Math.sin(a) * ringRadius * 0.58);
    const mid = new T.Vector3(pos.x * 0.5, pos.y * 0.5 + (i % 2 === 0 ? 0.45 : -0.45), pos.z * 0.5 + 0.35);
    nodePositions.push(pos);
    midPositions.push(mid);

    const spoke = new T.QuadraticBezierCurve3(new T.Vector3(0, 0, 0), mid, pos);
    group.add(new T.Line(pool.trackGeo(new T.BufferGeometry().setFromPoints(spoke.getPoints(28))), spokeMat));

    const ng = new T.Group();
    ng.position.copy(pos);
    ng.add(new T.Mesh(octGeo, nodeMat), new T.LineLoop(nodeRingGeo, nodeHaloMat));
    group.add(ng);
    nodeGroups.push(ng);
  }

  for (let i = 0; i < nodeCount; i++) {
    const start = nodePositions[i], end = nodePositions[(i + 1) % nodeCount];
    const arc = new T.QuadraticBezierCurve3(start, start.clone().add(end).multiplyScalar(0.54), end);
    group.add(new T.Line(pool.trackGeo(new T.BufferGeometry().setFromPoints(arc.getPoints(20))), perimeterMat));
  }

  // Pack all outward spoke pulses into one Points draw call.
  const perSpoke = small ? 2 : 4;
  const total = nodeCount * perSpoke;
  const mids = new Float32Array(total * 3);
  const ends = new Float32Array(total * 3);
  const offsets = new Float32Array(total);
  const speeds = new Float32Array(total);
  const sizes = new Float32Array(total);
  let idx = 0;
  for (let i = 0; i < nodeCount; i++) {
    const m = midPositions[i], e = nodePositions[i];
    for (let j = 0; j < perSpoke; j++) {
      mids[idx * 3] = m.x; mids[idx * 3 + 1] = m.y; mids[idx * 3 + 2] = m.z;
      ends[idx * 3] = e.x; ends[idx * 3 + 1] = e.y; ends[idx * 3 + 2] = e.z;
      offsets[idx] = j / perSpoke + (i / nodeCount) * 0.5;
      speeds[idx] = 0.26 + rand() * 0.06;
      sizes[idx] = 3.2 + rand() * 1.4;
      idx++;
    }
  }

  const pulseGeo = pool.trackGeo(new T.BufferGeometry());
  pulseGeo.setAttribute("position", new T.Float32BufferAttribute(new Float32Array(total * 3), 3));
  pulseGeo.setAttribute("aMid", new T.Float32BufferAttribute(mids, 3));
  pulseGeo.setAttribute("aEnd", new T.Float32BufferAttribute(ends, 3));
  pulseGeo.setAttribute("aOffset", new T.Float32BufferAttribute(offsets, 1));
  pulseGeo.setAttribute("aSpeed", new T.Float32BufferAttribute(speeds, 1));
  pulseGeo.setAttribute("aSize", new T.Float32BufferAttribute(sizes, 1));

  const pulseUniforms = {
    uTime: { value: 0 }, uPixelRatio: { value: dpr }, uOpacity: { value: 0 },
    uColor: { value: new T.Color(palette.networkPulse) },
  };
  const pulseMat = makeShaderMat(T, pool, { ...pulseUniforms }, PULSE_VERT, SOFT_DOT_FRAG, palette.blending);
  const pulses = new T.Points(pulseGeo, pulseMat);
  pulses.frustumCulled = false;
  group.add(pulses);
  group.visible = false;

  const allMats: THREE.Material[] = [spokeMat, perimeterMat, nodeMat, nodeHaloMat, pulseMat];
  return {
    group,
    applyTheme(next: ThemePalette): void {
      spokeMat.color.setHex(next.networkLine);
      perimeterMat.color.setHex(next.networkLine);
      nodeMat.color.setHex(next.networkNode);
      nodeHaloMat.color.setHex(next.networkLine);
      pulseUniforms.uColor.value.setHex(next.networkPulse);
      for (const m of allMats) setBlending(m, next.blending);
    },
    setPixelRatio(nextDpr: number): void { pulseUniforms.uPixelRatio.value = nextDpr; },
    update(elapsed: number, state: StoryState, active: ThemePalette): void {
      group.visible = state.networkOpacity > 0.005;
      if (!group.visible) return;
      group.position.x = state.coreOffsetX;
      group.rotation.y = elapsed * 0.075;
      group.scale.setScalar(0.84 + state.networkOpacity * 0.16);

      spokeMat.opacity = active.alpha.netLine * state.networkOpacity;
      perimeterMat.opacity = active.alpha.netLine * 0.55 * state.networkOpacity;
      nodeMat.opacity = active.alpha.netNode * state.networkOpacity;
      nodeHaloMat.opacity = active.alpha.netLine * 1.45 * state.networkOpacity;
      pulseUniforms.uTime.value = elapsed;
      pulseUniforms.uOpacity.value = active.alpha.netPulse * state.networkOpacity * state.networkPulse;

      for (let i = 0; i < nodeGroups.length; i++) {
        const ng = nodeGroups[i];
        ng.rotation.set(Math.sin(elapsed * 0.5 + i) * 0.3, elapsed * 0.45 + i, 0);
        ng.scale.setScalar(1 + 0.12 * Math.sin(elapsed * 1.8 - i * 0.9) * state.networkPulse);
      }
    },
  };
}

function buildStarfield(
  T: ThreeModule, pool: DisposablePool, small: boolean, rand: () => number, dpr: number, palette: ThemePalette,
): SceneActor {
  const group = new T.Group();
  const count = small ? 110 : 260;
  const pos = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const phases = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    pos[i * 3] = (rand() - 0.5) * 32;
    pos[i * 3 + 1] = (rand() - 0.5) * 20;
    pos[i * 3 + 2] = -20 + rand() * 22;
    sizes[i] = 1.2 + rand() * 2.1;
    phases[i] = rand() * Math.PI * 2;
  }

  const geo = pool.trackGeo(new T.BufferGeometry());
  geo.setAttribute("position", new T.Float32BufferAttribute(pos, 3));
  geo.setAttribute("aSize", new T.Float32BufferAttribute(sizes, 1));
  geo.setAttribute("aPhase", new T.Float32BufferAttribute(phases, 1));
  const uniforms = {
    uTime: { value: 0 }, uPixelRatio: { value: dpr }, uOpacity: { value: palette.alpha.stars * 0.28 },
    uColor: { value: new T.Color(palette.stars) },
  };
  const mat = makeShaderMat(T, pool, { ...uniforms }, STAR_VERT, SOFT_DOT_FRAG, palette.blending);
  group.add(new T.Points(geo, mat));

  return {
    group,
    applyTheme(next: ThemePalette): void {
      uniforms.uColor.value.setHex(next.stars);
      setBlending(mat, next.blending);
    },
    setPixelRatio(nextDpr: number): void { uniforms.uPixelRatio.value = nextDpr; },
    update(elapsed: number, state: StoryState, active: ThemePalette): void {
      group.rotation.y = elapsed * 0.012;
      uniforms.uTime.value = elapsed;
      uniforms.uOpacity.value = active.alpha.stars * state.starfieldOpacity;
    },
  };
}

function buildScrollTimeline(state: StoryState): GsapTimelineLike | null {
  const win = window as WindowWithGsap;
  const mainEl = document.querySelector("main");
  if (!win.gsap || !win.ScrollTrigger || !mainEl) return null;

  win.gsap.registerPlugin(win.ScrollTrigger);
  const mainRect = mainEl.getBoundingClientRect();
  const mainTop = mainRect.top + window.scrollY;
  const scrollable = Math.max(1, mainRect.height - window.innerHeight);
  const anchorOffset = window.innerHeight * 0.45;
  const progressOf = (el: Element | null, fallback: number): number => (
    el ? clamp((el.getBoundingClientRect().top + window.scrollY - mainTop - anchorOffset) / scrollable, 0.06, 0.94) : fallback
  );

  const netEls = document.querySelectorAll('[data-chapter="network"]');
  const streams = Math.min(0.6, progressOf(document.querySelector('[data-chapter="streams"]'), 0.24));
  const docs = Math.min(0.71, Math.max(streams + 0.09, progressOf(document.querySelector('[data-chapter="documents"]'), 0.42)));
  const netStart = Math.min(0.81, Math.max(docs + 0.1, progressOf(netEls[0] ?? null, 0.6)));
  const netEnd = Math.min(0.86, Math.max(netStart + 0.06, progressOf(netEls[netEls.length - 1] ?? null, 0.72)));
  const starfield = Math.min(0.92, Math.max(netEnd + 0.07, progressOf(document.querySelector('[data-chapter="starfield"]'), 0.8)));

  // Keep transition windows strictly disjoint so scrubbed tweens never fight each other.
  const w1 = Math.min(0.05, streams * 0.35, (docs - streams) * 0.35);
  const w2 = Math.min(0.05, (docs - streams) * 0.35, (netStart - docs) * 0.35);
  const w3 = Math.min(0.05, (netStart - docs) * 0.35, (starfield - netStart) * 0.3);
  const w4 = Math.min(0.055, (starfield - netEnd) * 0.45, (1 - starfield) * 0.4);

  const s1Start = Math.max(0.02, streams - w1), s1End = streams + w1;
  const s2Start = Math.max(s1End + 0.01, docs - w2), s2End = docs + w2;
  const s3Start = Math.max(s2End + 0.01, netStart - w3), s3End = netStart + w3;
  const s4Start = Math.max(s3End + 0.01, starfield - w4), s4End = Math.min(0.97, starfield + w4);

  const tl = win.gsap.timeline({
    defaults: { ease: "sine.inOut" },
    scrollTrigger: {
      trigger: mainEl, start: "top top", end: "bottom bottom", scrub: 1.15,
      // Calculate after landing-motion.js inserts #cinema's pin spacer.
      refreshPriority: -1, invalidateOnRefresh: true,
    },
  });

  tl.to(state, { camZ: 7.0, camY: 0.22, coreOffsetX: isSmallScreen() ? 0 : 1.25, duration: s1Start }, 0);
  tl.to(state, {
    // Right of the three step texts, so wireframe lines do not cross the copy on wide screens.
    camX: -0.35, camY: 0.35, camZ: 6.65, coreOffsetX: isSmallScreen() ? 0 : 1.7,
    corePulse: 0.55, haloOpacity: 0.52, streamsOpacity: 1, duration: s1End - s1Start,
  }, s1Start);
  tl.to(state, { camX: -0.15, camY: 0.28, duration: Math.max(0.01, s2Start - s1End) }, s1End);
  tl.to(state, {
    camX: 0.65, camY: 0.22, camZ: 6.45, coreOffsetX: 0, coreScale: 0.92,
    corePulse: 0.65, haloOpacity: 0.38, streamsOpacity: 0, docsOpacity: 1, duration: s2End - s2Start,
  }, s2Start);
  tl.to(state, { camX: 0.3, camY: 0.45, docsFlow: 1, duration: Math.max(0.01, s3Start - s2End) }, s2End);
  tl.to(state, {
    camX: 0, camY: 1.2, camZ: 7.45, lookY: -0.08, coreScale: 0.86, corePulse: 0.72,
    haloOpacity: 0.3, docsOpacity: 0, networkOpacity: 1, networkPulse: 1, duration: s3End - s3Start,
  }, s3Start);
  tl.to(state, { camX: -0.45, camY: 1.0, camZ: 7.8, duration: Math.max(0.01, s4Start - s3End) }, s3End);
  tl.to(state, {
    camX: 0, camY: 0.28, camZ: 12.2, lookY: 0, coreScale: 0.52, coreOpacity: 0.14, corePulse: 0.08,
    haloOpacity: 0.12, networkOpacity: 0, networkPulse: 0, starfieldOpacity: 0.78, duration: s4End - s4Start,
  }, s4Start);
  tl.to(state, { camZ: 13.0, camY: 0.45, duration: Math.max(0.01, 1 - s4End) }, s4End);

  return tl;
}

function mountScene(T: ThreeModule, canvas: HTMLCanvasElement, onDispose: () => void): boolean {
  const small = isSmallScreen();
  let dpr = getCappedPixelRatio();

  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new T.WebGLRenderer({ canvas, alpha: true, antialias: !small, powerPreference: "high-performance" });
  } catch {
    return false;
  }
  const initWidth = Math.max(1, window.innerWidth), initHeight = Math.max(1, window.innerHeight);
  renderer.outputColorSpace = T.SRGBColorSpace;
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(dpr);
  renderer.setSize(initWidth, initHeight, false);

  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(44, initWidth / initHeight, 0.1, 60);
  const state = createInitialStoryState();
  const pool = createDisposablePool();
  const rand = createSeededRandom(20261127);
  const palettes = createPalettes(T);
  let activePalette: ThemePalette = palettes[readTheme()];

  const actors: SceneActor[] = [
    buildStarfield(T, pool, small, rand, dpr, activePalette),
    buildCore(T, pool, small, rand, dpr, activePalette),
    buildStreams(T, pool, small, rand, dpr, activePalette),
    buildDocuments(T, pool, small, rand, activePalette),
    buildNetwork(T, pool, small, rand, dpr, activePalette),
  ];
  for (const actor of actors) scene.add(actor.group);

  const syncTimeline = (tl: GsapTimelineLike | null): void => {
    if (!tl) return;
    const p = tl.scrollTrigger?.progress ?? 0;
    tl.progress(p);
    tl.scrollTrigger?.getTween?.()?.progress(1);
  };

  let timeline: GsapTimelineLike | null = buildScrollTimeline(state);
  if (timeline) {
    (window as WindowWithGsap).ScrollTrigger?.refresh();
    syncTimeline(timeline);
  }

  const rebuildTimeline = (): void => {
    if (timeline) {
      timeline.scrollTrigger?.kill();
      timeline.kill();
      timeline = null;
    }
    (window as WindowWithGsap).ScrollTrigger?.refresh();
    Object.assign(state, createInitialStoryState());
    timeline = buildScrollTimeline(state);
    syncTimeline(timeline);
  };

  let rafId = 0, elapsed = 0, lastNow = performance.now();
  let disposed = false, contextLost = false;

  const renderFrame = (now: number): void => {
    rafId = 0;
    if (disposed || document.hidden || contextLost) return;
    elapsed += Math.min(0.05, Math.max(0, (now - lastNow) / 1000));
    lastNow = now;
    camera.position.set(state.camX, state.camY, state.camZ);
    camera.lookAt(state.lookX, state.lookY, 0);
    for (const actor of actors) actor.update(elapsed, state, activePalette);
    renderer.render(scene, camera);
    rafId = window.requestAnimationFrame(renderFrame);
  };

  const startLoop = (): void => {
    if (disposed || rafId !== 0 || document.hidden || contextLost) return;
    lastNow = performance.now();
    rafId = window.requestAnimationFrame(renderFrame);
  };

  const stopLoop = (): void => {
    if (rafId !== 0) { window.cancelAnimationFrame(rafId); rafId = 0; }
  };

  const onVisibilityChange = (): void => (document.hidden ? stopLoop() : startLoop());

  let lastWidth = initWidth, lastHeight = initHeight;
  let resizeTimer = 0, langTimer = 0;
  const onResize = (): void => {
    if (disposed) return;
    const width = Math.max(1, window.innerWidth), height = Math.max(1, window.innerHeight);
    dpr = getCappedPixelRatio();
    renderer.setPixelRatio(dpr);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    for (const actor of actors) actor.setPixelRatio(dpr);
    if (width !== lastWidth || Math.abs(height - lastHeight) > 120) {
      lastWidth = width;
      lastHeight = height;
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => { if (!disposed) rebuildTimeline(); }, 180);
    }
  };

  const onLanguageChange = (): void => {
    if (disposed) return;
    window.clearTimeout(langTimer);
    langTimer = window.setTimeout(() => { if (!disposed) rebuildTimeline(); }, 60);
  };
  const onContextLost = (e: Event): void => { e.preventDefault(); contextLost = true; stopLoop(); };
  const onContextRestored = (): void => { contextLost = false; startLoop(); };

  const themeObserver = new MutationObserver(() => {
    const next = palettes[readTheme()];
    if (next === activePalette) return;
    activePalette = next;
    for (const actor of actors) actor.applyTheme(activePalette);
  });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  const motionQuery = window.matchMedia?.("(prefers-reduced-motion: reduce)") ?? null;
  const onMotionChange = (e: MediaQueryListEvent): void => { if (e.matches) dispose(); };

  const dispose = (): void => {
    if (disposed) return;
    disposed = true;
    stopLoop();
    window.clearTimeout(resizeTimer);
    window.clearTimeout(langTimer);
    themeObserver.disconnect();
    if (timeline) {
      timeline.scrollTrigger?.kill();
      timeline.kill();
      timeline = null;
    }
    document.removeEventListener("visibilitychange", onVisibilityChange);
    window.removeEventListener("resize", onResize);
    document.removeEventListener("omnexa:languagechange", onLanguageChange);
    canvas.removeEventListener("webglcontextlost", onContextLost);
    canvas.removeEventListener("webglcontextrestored", onContextRestored);
    motionQuery?.removeEventListener("change", onMotionChange);
    window.removeEventListener("pagehide", dispose);
    scene.clear();
    pool.disposeAll();
    renderer.dispose();
    canvas.classList.remove("is-ready");
    onDispose();
  };

  document.addEventListener("visibilitychange", onVisibilityChange);
  window.addEventListener("resize", onResize, { passive: true });
  document.addEventListener("omnexa:languagechange", onLanguageChange);
  canvas.addEventListener("webglcontextlost", onContextLost);
  canvas.addEventListener("webglcontextrestored", onContextRestored);
  motionQuery?.addEventListener("change", onMotionChange);
  window.addEventListener("pagehide", dispose, { once: true });

  // Render the initial frame before fading in so the first visible paint is populated.
  camera.position.set(state.camX, state.camY, state.camZ);
  camera.lookAt(state.lookX, state.lookY, 0);
  for (const actor of actors) actor.update(0, state, activePalette);
  renderer.render(scene, camera);
  canvas.classList.add("is-ready");
  startLoop();
  return true;
}

export function initLandingScene(): void {
  const canvas = document.getElementById("landing-scene");
  if (!(canvas instanceof HTMLCanvasElement) || shouldSkipScene()) return;

  let cancelled = false;
  let mounted = false;
  let booting = false;
  let bootToken = 0;
  let idleHandle: number | null = null;
  let timeoutHandle: number | null = null;

  const boot = async (): Promise<void> => {
    if (cancelled || mounted || booting || shouldSkipScene() || !isWebGLAvailable()) return;
    const token = bootToken;
    booting = true;
    try {
      const threeModule = await import("./three-subset");
      if (cancelled || token !== bootToken || mounted || shouldSkipScene()) return;
      mounted = mountScene(threeModule, canvas, () => { mounted = false; });
    } catch {
      // Leave the static HTML page intact if WebGL or chunk loading fails.
    } finally {
      if (token === bootToken) booting = false;
    }
  };

  const scheduleIdle = (): void => {
    if (cancelled || mounted || booting || idleHandle !== null || timeoutHandle !== null) return;
    const win = window as WindowWithIdle;
    if (typeof win.requestIdleCallback === "function") {
      idleHandle = win.requestIdleCallback(() => { idleHandle = null; void boot(); }, { timeout: 1800 });
    } else {
      timeoutHandle = window.setTimeout(() => { timeoutHandle = null; void boot(); }, 200);
    }
  };

  const cancelPending = (): void => {
    cancelled = true;
    bootToken++;
    booting = false;
    const win = window as WindowWithIdle;
    if (idleHandle !== null && typeof win.cancelIdleCallback === "function") {
      win.cancelIdleCallback(idleHandle);
      idleHandle = null;
    }
    if (timeoutHandle !== null) {
      window.clearTimeout(timeoutHandle);
      timeoutHandle = null;
    }
  };

  window.addEventListener("pagehide", cancelPending);
  window.addEventListener("pageshow", (e: PageTransitionEvent) => {
    if (e.persisted && !mounted && !shouldSkipScene()) {
      cancelled = false;
      scheduleIdle();
    }
  });
  if (document.readyState === "complete") scheduleIdle();
  else window.addEventListener("load", scheduleIdle, { once: true });
}
