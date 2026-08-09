/** Minimal declaration for three's OrbitControls example module. */
declare module "three/examples/jsm/controls/OrbitControls.js" {
  export class OrbitControls {
    constructor(
      camera: unknown,
      domElement: unknown,
    );
    enableDamping: boolean;
    autoRotate: boolean;
    autoRotateSpeed: number;
    target: { set(x: number, y: number, z: number): void };
    minDistance: number;
    maxDistance: number;
    update(): void;
    dispose(): void;
  }
}
