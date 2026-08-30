export function Hero() {
  return (
    <section className="hero">
      <div>
        <p className="eyebrow">Evidence-aware runtime governance</p>
        <h1>
          Trust the decision,
          <br />
          <span>not just the response.</span>
        </h1>
        <p className="hero-copy">
          Each AI use case gets its own evidence requirements, risk budget and intervention
          policy—before output becomes binding.
        </p>
      </div>
      <div className="flow-card" aria-label="Runtime pipeline">
        <div className="flow-step active">
          <b>01</b>
          <span>Route</span>
          <small>profile + action</small>
        </div>
        <div className="flow-line" />
        <div className="flow-step">
          <b>02</b>
          <span>Check</span>
          <small>parallel evidence</small>
        </div>
        <div className="flow-line" />
        <div className="flow-step">
          <b>03</b>
          <span>Decide</span>
          <small>allow → block</small>
        </div>
        <div className="flow-line" />
        <div className="flow-step">
          <b>04</b>
          <span>Prove</span>
          <small>versioned audit</small>
        </div>
      </div>
    </section>
  );
}
