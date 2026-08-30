type TopBarProps = {
  online: boolean;
  apiVersion: string;
};

export function TopBar({ online, apiVersion }: TopBarProps) {
  return (
    <header className="topbar">
      <a className="brand" href="#">
        <span className="brand-mark">CP</span>
        <span>
          ControlPlane<span className="brand-dot">.ai</span>
        </span>
      </a>
      <div className="runtime">
        <span className={`pulse ${online ? "online" : ""}`} />
        deterministic demo {online && apiVersion ? `· ${apiVersion}` : "· connecting"}
      </div>
    </header>
  );
}
