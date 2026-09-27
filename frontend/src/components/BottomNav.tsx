/** 底部固定导航(五栏):社区 / 图鉴 / ➕创建 / 管理 / 个人。
 *  ➕ 是**主按钮**(进创建流程),不是 tab。 */
export type HomeTab = "community" | "collection" | "manage" | "profile";

const ITEMS: { key: HomeTab; label: string; icon: string }[] = [
  { key: "community", label: "社区", icon: "🏘️" },
  { key: "collection", label: "图鉴", icon: "🗺️" },
  { key: "manage", label: "管理", icon: "🧳" },
  { key: "profile", label: "个人", icon: "👤" },
];

interface Props {
  tab: HomeTab;
  onTab: (t: HomeTab) => void;
  onCreate: () => void;
}

export default function BottomNav({ tab, onTab, onCreate }: Props) {
  return (
    <nav className="bottom-nav">
      <div className="bottom-nav-item" onClick={() => onTab("community")}>
        <span className={`bn-icon ${tab === "community" ? "active" : ""}`}>🏘️</span>
        <span className={`bn-label ${tab === "community" ? "active" : ""}`}>社区</span>
      </div>
      <div className="bottom-nav-item" onClick={() => onTab("collection")}>
        <span className={`bn-icon ${tab === "collection" ? "active" : ""}`}>🗺️</span>
        <span className={`bn-label ${tab === "collection" ? "active" : ""}`}>图鉴</span>
      </div>
      <button className="bn-create" onClick={onCreate} title="创建新计划">
        <span className="bn-create-plus">＋</span>
        <span className="bn-create-label">创建</span>
      </button>
      <div className="bottom-nav-item" onClick={() => onTab("manage")}>
        <span className={`bn-icon ${tab === "manage" ? "active" : ""}`}>🧳</span>
        <span className={`bn-label ${tab === "manage" ? "active" : ""}`}>管理</span>
      </div>
      <div className="bottom-nav-item" onClick={() => onTab("profile")}>
        <span className={`bn-icon ${tab === "profile" ? "active" : ""}`}>👤</span>
        <span className={`bn-label ${tab === "profile" ? "active" : ""}`}>个人</span>
      </div>
    </nav>
  );
}