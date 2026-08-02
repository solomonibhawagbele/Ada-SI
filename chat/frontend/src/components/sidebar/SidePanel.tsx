import { useEffect } from "react"
import { useToolBuildStream } from "../../hooks/useToolBuildStream"
import { useAppStore } from "../../state/store"
import { PackagesTab } from "./PackagesTab"
import { QuickActions } from "./QuickActions"
import { ToolsTab } from "./ToolsTab"

export function SidePanel() {
  const activeTab = useAppStore((s) => s.activeSidePanelTab)
  const setActiveTab = useAppStore((s) => s.setActiveSidePanelTab)
  const tools = useAppStore((s) => s.tools)
  const packages = useAppStore((s) => s.packages)
  const appConfig = useAppStore((s) => s.appConfig)
  const { refreshTools, refreshPackages } = useToolBuildStream()

  useEffect(() => {
    refreshTools()
    if (appConfig.tools?.length) {
      useAppStore.getState().setTools(appConfig.tools)
    }
  }, [])

  useEffect(() => {
    if (activeTab === "packages") {
      refreshPackages()
    }
  }, [activeTab])

  return (
    <aside className="side-panel tools-panel glass-panel">
      <div className="panel-header">
        <div className="panel-tabs" role="tablist" aria-label="Skill loadout sidebar">
          <button
            type="button"
            className={`panel-tab${activeTab === "tools" ? " active" : ""}`}
            role="tab"
            aria-selected={activeTab === "tools"}
            onClick={() => setActiveTab("tools")}
          >
            Skills
          </button>
          <button
            type="button"
            className={`panel-tab${activeTab === "packages" ? " active" : ""}`}
            role="tab"
            aria-selected={activeTab === "packages"}
            onClick={() => setActiveTab("packages")}
          >
            Supplies
          </button>
          <button
            type="button"
            className={`panel-tab${activeTab === "actions" ? " active" : ""}`}
            role="tab"
            aria-selected={activeTab === "actions"}
            onClick={() => setActiveTab("actions")}
          >
            Actions
          </button>
        </div>
        <div className="panel-title-row">
          <h2>{
            activeTab === "packages" ? "Supply Cache" : 
            activeTab === "actions" ? "Quick Actions" : 
            "Skill Loadout"
          }</h2>
          {activeTab === "tools" ? (
            <span className="panel-badge">{tools.length}</span>
          ) : activeTab === "packages" ? (
            <span className="panel-badge">{packages.length}</span>
          ) : null}
        </div>
      </div>
      <div className={`tools-list scroll-area${activeTab !== "tools" ? " hidden" : ""}`}>
        <ToolsTab tools={tools} />
      </div>
      <div className={`tools-list scroll-area${activeTab !== "packages" ? " hidden" : ""}`}>
        <PackagesTab packages={packages} />
      </div>
      <div className={`tools-list scroll-area${activeTab !== "actions" ? " hidden" : ""}`}>
        <QuickActions />
      </div>
    </aside>
  )
}
