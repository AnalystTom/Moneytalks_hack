import { Component, Suspense, useEffect, useMemo } from "react";
import type { ReactNode } from "react";
import { Canvas, useLoader } from "@react-three/fiber";
import { Billboard, Html } from "@react-three/drei";
import { SRGBColorSpace, TextureLoader } from "three";
import { members, sourceUrl } from "./contract";
import type { Member, Source, Verdict } from "./contract";

type Props = {
  active?: Member;
  statuses: Partial<Record<Member, string>>;
  verdicts: Partial<Record<Member, Verdict>>;
  sources: Partial<Record<Member, Source[]>>;
  onSelect: (member: Member) => void;
};
function useScenePalette() {
  return useMemo(() => {
    const style = getComputedStyle(document.documentElement);
    return (name: string) => style.getPropertyValue(`--${name}`).trim();
  }, []);
}
const seats: {
  member: Member;
  position: [number, number, number];
  scale: number;
}[] = [
  { member: "buffett", position: [0, 2.25, -3.5], scale: 2.65 },
  { member: "leopold", position: [-3.1, 2.1, 0], scale: 2.55 },
  { member: "burry", position: [2.75, 2.1, -1.1], scale: 2.45 },
  { member: "cramer", position: [3.75, 2.05, 2.3], scale: 2.5 },
];
function Portrait({
  member,
  position,
  scale,
  active,
  statuses,
  verdicts,
  sources,
  onSelect,
}: Props & (typeof seats)[number]) {
  const color = useScenePalette();
  const atlas = useLoader(TextureLoader, "/council-portraits.png");
  const texture = useMemo(() => {
    const tile = atlas.clone();
    tile.colorSpace = SRGBColorSpace;
    tile.repeat.set(0.5, 0.5);
    tile.offset.set(
      members[member].tile[0] * 0.5,
      members[member].tile[1] * 0.5,
    );
    return tile;
  }, [atlas, member]);
  useEffect(() => () => texture.dispose(), [texture]);
  const selected = active === member;
  const verdict = verdicts[member];
  return (
    <group position={position}>
      <Billboard>
        <mesh onClick={() => onSelect(member)}>
          <planeGeometry args={[scale, scale]} />
          <meshBasicMaterial
            map={texture}
            toneMapped={false}
            color={
              active && !selected ? color("scene-dim") : color("scene-white")
            }
          />
        </mesh>
        <mesh position={[0, 0, -0.025]}>
          <boxGeometry args={[scale + 0.07, scale + 0.07, 0.05]} />
          <meshStandardMaterial
            color={selected ? color("gold") : color("scene-frame")}
            metalness={0.7}
            roughness={0.3}
          />
        </mesh>
      </Billboard>
      <Html position={[0, -scale / 2 - 0.13, 0.3]} center zIndexRange={[5, 0]}>
        <button
          className={`seat-label ${selected ? "speaking" : ""}`}
          onClick={() => onSelect(member)}
          aria-label={`View ${members[member].name}`}
        >
          <span>{members[member].name}</span>
          <small>
            {verdict
              ? `${verdict.signal} · View more ↗`
              : statuses[member] || "Ready to listen"}
          </small>
          {statuses[member] && !verdict && (
            <small className="seat-source">
              {sources[member]?.filter((source) => sourceUrl(source.url)).at(-1)
                ?.title || "Sources unavailable"}
            </small>
          )}
        </button>
      </Html>
      {selected && verdict && (
        <Html
          position={[0, -scale / 2 - 0.9, 1.05]}
          center
          zIndexRange={[6, 0]}
        >
          <button className="table-verdict" onClick={() => onSelect(member)}>
            <span className={`signal ${verdict.signal.toLowerCase()}`}>
              {verdict.signal}
            </span>
            <small>{Math.round(verdict.confidence * 100)}% CONFIDENCE</small>
            <strong>{verdict.headline}</strong>
            <span>View more ↗</span>
          </button>
        </Html>
      )}
    </group>
  );
}
function Room(props: Props) {
  const color = useScenePalette();
  return (
    <>
      <color attach="background" args={[color("background")]} />
      <fog attach="fog" args={[color("background"), 17, 35]} />
      <ambientLight intensity={1.1} />
      <hemisphereLight args={[color("scene-fill"), color("panel"), 1.7]} />
      <pointLight
        position={[0, 6, 2]}
        color={color("scene-light")}
        intensity={65}
      />
      <mesh position={[0, -0.4, 0]}>
        <boxGeometry args={[30, 0.3, 30]} />
        <meshStandardMaterial color={color("scene-floor")} />
      </mesh>
      <mesh position={[0, 3, -5.8]}>
        <boxGeometry args={[20, 8, 0.3]} />
        <meshStandardMaterial color={color("scene-wall")} />
      </mesh>
      {Array.from({ length: 13 }, (_, i) => (
        <mesh key={i} position={[-9 + i * 1.5, 3, -5.5]}>
          <boxGeometry args={[0.05, 8, 0.08]} />
          <meshStandardMaterial
            color={color("scene-frame")}
            metalness={0.4}
            roughness={0.6}
          />
        </mesh>
      ))}
      <mesh position={[0, 0.63, 1.5]}>
        <boxGeometry args={[5.8, 0.3, 10.5]} />
        <meshStandardMaterial
          color={color("scene-table")}
          roughness={0.33}
          metalness={0.12}
        />
      </mesh>
      <mesh position={[0, 0.79, 1.5]}>
        <boxGeometry args={[4.8, 0.025, 9.7]} />
        <meshStandardMaterial color={color("scene-felt")} roughness={0.7} />
      </mesh>
      {[-1, 1].map((side) => (
        <group key={side} position={[side * 2.35, 0.85, 2.6]}>
          <mesh>
            <cylinderGeometry args={[0.29, 0.36, 0.08, 24]} />
            <meshStandardMaterial
              color={color("scene-brass")}
              metalness={0.8}
              roughness={0.25}
            />
          </mesh>
          <mesh position={[0, 0.35, 0]}>
            <cylinderGeometry args={[0.035, 0.035, 0.65, 16]} />
            <meshStandardMaterial
              color={color("scene-brass")}
              metalness={0.8}
              roughness={0.25}
            />
          </mesh>
          <mesh position={[0, 0.76, 0]}>
            <coneGeometry args={[0.42, 0.3, 24]} />
            <meshStandardMaterial
              color={color("gold")}
              emissive={color("gold")}
              emissiveIntensity={0.45}
            />
          </mesh>
          <pointLight
            position={[0, 0.65, 0]}
            color={color("scene-light")}
            intensity={8}
            distance={5}
          />
        </group>
      ))}
      {seats.map((seat) => (
        <Portrait key={seat.member} {...props} {...seat} />
      ))}
    </>
  );
}
class SceneBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div className="scene-fallback">
        The 3D boardroom is unavailable on this device. The council transcript
        and controls remain available.
      </div>
    ) : (
      this.props.children
    );
  }
}
export default function Boardroom(props: Props) {
  return (
    <SceneBoundary>
      <Suspense
        fallback={<div className="scene-fallback">Lighting the boardroom…</div>}
      >
        <Canvas
          camera={{ position: [0, 4.6, 11.5], fov: 49 }}
          onCreated={({ camera }) => camera.lookAt(0, 1.65, 0)}
          dpr={[1, 1.75]}
          gl={{ antialias: true }}
        >
          <Room {...props} />
        </Canvas>
      </Suspense>
    </SceneBoundary>
  );
}
