import { useRef } from "react";
export function Signature({ onChange }: { onChange: (value: string) => void }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  function point(e: React.PointerEvent<HTMLCanvasElement>) {
    const c = e.currentTarget,
      r = c.getBoundingClientRect();
    return [
      ((e.clientX - r.left) * c.width) / r.width,
      ((e.clientY - r.top) * c.height) / r.height,
    ];
  }
  return (
    <div className="field">
      <span>Customer signature — draw to acknowledge the resolution below</span>
      <canvas
        aria-label="Customer signature pad"
        ref={ref}
        width={600}
        height={180}
        style={{
          width: "100%",
          height: 180,
          touchAction: "none",
          border: "1px solid #72868c",
          background: "white",
        }}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          drawing.current = true;
          const ctx = e.currentTarget.getContext("2d")!;
          ctx.lineWidth = 3;
          ctx.beginPath();
          const [x, y] = point(e);
          ctx.moveTo(x, y);
        }}
        onPointerMove={(e) => {
          if (drawing.current) {
            const ctx = e.currentTarget.getContext("2d")!;
            const [x, y] = point(e);
            ctx.lineTo(x, y);
            ctx.stroke();
          }
        }}
        onPointerUp={() => {
          drawing.current = false;
          onChange(ref.current!.toDataURL("image/png").split(",")[1]);
        }}
      />
      <button
        type="button"
        className="secondary"
        onClick={() => {
          ref.current!.getContext("2d")!.clearRect(0, 0, 600, 180);
          onChange("");
        }}
      >
        Clear signature
      </button>
    </div>
  );
}
export async function imageData(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const canvas = document.createElement("canvas");
  const ratio = Math.min(1, 640 / Math.max(bitmap.width, bitmap.height));
  canvas.width = bitmap.width * ratio;
  canvas.height = bitmap.height * ratio;
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  let data = canvas.toDataURL("image/jpeg", 0.65).split(",")[1];
  if (data.length > 55000)
    data = canvas.toDataURL("image/jpeg", 0.3).split(",")[1];
  if (data.length > 55000)
    throw new Error("Photo is too detailed. Choose a smaller image.");
  return data;
}
