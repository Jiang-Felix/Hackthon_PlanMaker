/**
 * 图片处理:把用户选的照片压到可内嵌的体积。
 *
 * 内存态演示不做文件上传 —— 照片以 base64 data URL 直接存进帖子(见 backend PostPhoto),
 * 所以这里要主动缩图,否则一篇帖子会把社区接口撑大。
 */

/** 单张照片 data URL 长度上限(约 300KB 原图),与后端校验口径对齐。 */
export const MAX_PHOTO_CHARS = 400_000;

export function isImageFile(file: File): boolean {
  return file.type.startsWith("image/");
}

type Loaded = HTMLImageElement;

function loadImage(file: File): Promise<Loaded> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("这个格式的图片打不开,请换 JPG 或 PNG"));
    };
    img.src = url;
  });
}

function drawToDataUrl(img: Loaded, maxEdge: number, quality: number): string {
  const sw = img.naturalWidth || img.width;
  const sh = img.naturalHeight || img.height;
  const scale = Math.min(1, maxEdge / Math.max(sw, sh));
  const w = Math.max(1, Math.round(sw * scale));
  const h = Math.max(1, Math.round(sh * scale));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("当前浏览器不支持图片压缩");
  ctx.drawImage(img, 0, 0, w, h);
  // 统一转 JPEG:体积远小于 PNG,旅游照片也不需要透明通道
  return canvas.toDataURL("image/jpeg", quality);
}

/** 等比压缩后返回 JPEG data URL;仍超限则再降一档,再不行抛错。 */
export async function fileToDataUrl(file: File, maxEdge = 1000, quality = 0.7): Promise<string> {
  const img = await loadImage(file);
  const first = drawToDataUrl(img, maxEdge, quality);
  if (first.length <= MAX_PHOTO_CHARS) return first;
  const smaller = drawToDataUrl(img, Math.round(maxEdge * 0.7), Math.max(0.4, quality - 0.1));
  if (smaller.length <= MAX_PHOTO_CHARS) return smaller;
  throw new Error("这张照片太大了,请换一张小一点的");
}
