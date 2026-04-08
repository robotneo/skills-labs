const VCENTER_KEYWORDS = [
  "vm", "虚拟机",
  "vcenter",
  "esxi",
  "datastore", "数据存储",
  "开机", "启动",
  "关机", "停止",
  "快照", "snapshot",
  "克隆", "clone",
  "创建虚拟机", "新建虚拟机",
  "删除", "delete"
];

const HIGH_RISK_ACTIONS = ["删除", "delete", "销毁", "destroy"];

const isVCenterIntent = (text: string) => {
  const lower = text.toLowerCase();
  const hits = VCENTER_KEYWORDS.filter(k => lower.includes(k)).length;
  return hits >= 1;
};

const isHighRisk = (text: string) => {
  const lower = text.toLowerCase();
  return HIGH_RISK_ACTIONS.some(k => lower.includes(k));
};

const handler = async (event: any) => {
  if (event.type !== "message" || event.action !== "preprocessed") return;

  const body = event.context?.bodyForAgent;
  if (!body || typeof body !== "string") return;

  // 排除命令消息（/new, /reset 等）
  if (body.startsWith("/")) return;

  if (!isVCenterIntent(body)) return;

  const user = event.context?.from || event.context?.senderId || "unknown";
  const riskLevel = isHighRisk(body) ? "🔴 HIGH_RISK" : "🟢 NORMAL";
  console.log(`[vcenter-guard] ${riskLevel} | User: ${user} | Body: ${body}`);
};

export default handler;