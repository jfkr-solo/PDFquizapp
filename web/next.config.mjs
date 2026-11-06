/** 静的書き出し：out/ をそのままVercelや任意の静的ホスティングに置ける */
const nextConfig = { output: "export", images: { unoptimized: true }, trailingSlash: true };
export default nextConfig;
