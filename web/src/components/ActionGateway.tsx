"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type {
  ActionProposal,
  CommerceOrder,
  GovernedAction,
} from "@/types/api";

type Props = { onNotify: (message: string) => void; onAction?: () => void };

function unwrapAction(value: ActionProposal | GovernedAction): GovernedAction {
  return "action" in value ? value.action : value;
}

function tokenFrom(value: ActionProposal | GovernedAction): string | null {
  if ("action" in value) return value.authorization_token ?? value.action.authorization_token ?? null;
  return value.authorization_token ?? null;
}

function money(value: number | null | undefined) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value ?? 0);
}

export function ActionGateway({ onNotify, onAction }: Props) {
  const [orders, setOrders] = useState<CommerceOrder[]>([]);
  const [actions, setActions] = useState<GovernedAction[]>([]);
  const [orderId, setOrderId] = useState("");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("wrong_item");
  const [active, setActive] = useState<GovernedAction | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [reviewAmount, setReviewAmount] = useState("");
  const [reviewNote, setReviewNote] = useState("Verified against the order system of record.");
  const [busy, setBusy] = useState<string | null>(null);

  const selectedOrder = useMemo(
    () => orders.find((order) => order.order_id === orderId) ?? null,
    [orders, orderId],
  );

  async function refresh(preferredId?: string) {
    const [nextOrders, nextActions] = await Promise.all([api.commerceOrders(), api.actions()]);
    setOrders(nextOrders);
    setActions(nextActions);
    const nextOrderId = orderId || nextOrders[0]?.order_id || "";
    setOrderId(nextOrderId);
    const matching = nextOrders.find((item) => item.order_id === nextOrderId);
    if (!amount && matching) setAmount(String(matching.order_total_inr));
    if (preferredId) {
      const refreshed = nextActions.find((item) => item.action_id === preferredId);
      if (refreshed) setActive(refreshed);
    }
  }

  useEffect(() => {
    refresh().catch((error) => onNotify(error instanceof Error ? error.message : "Action Gateway unavailable"));
    // Bootstrap once; user operations explicitly refresh the ledger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function chooseOrder(order: CommerceOrder) {
    setOrderId(order.order_id);
    setAmount(String(order.order_total_inr));
    setReviewAmount(String(order.order_total_inr));
    setActive(null);
    setToken(null);
  }

  async function propose() {
    if (!orderId || !Number.isFinite(Number(amount))) return;
    setBusy("propose");
    try {
      const result = await api.proposeAction({
        use_case: "refund_agent",
        region: "IN",
        session_id: `judge-demo-${orderId}`,
        order_id: orderId,
        amount_inr: Number(amount),
        reason,
      });
      const action = unwrapAction(result);
      setActive(action);
      setToken(tokenFrom(result));
      setReviewAmount(String(selectedOrder?.order_total_inr ?? action.amount_inr));
      await refresh(action.action_id);
      onNotify(`Action ${action.decision.replaceAll("_", " ")}: execution remains policy-controlled`);
      onAction?.();
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Proposal failed");
    } finally {
      setBusy(null);
    }
  }

  async function review(decision: "approve" | "reject") {
    if (!active) return;
    setBusy(decision);
    try {
      const result = await api.reviewAction(active.action_id, {
        decision,
        ...(decision === "approve" && reviewAmount
          ? { corrected_amount_inr: Number(reviewAmount) }
          : {}),
        note: reviewNote,
      });
      const action = unwrapAction(result);
      setActive(action);
      setToken(tokenFrom(result));
      await refresh(action.action_id);
      onNotify(decision === "approve" ? "Reviewer approved a constrained action" : "Action rejected and contained");
      onAction?.();
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Review failed");
    } finally {
      setBusy(null);
    }
  }

  async function execute() {
    if (!active || !token) return;
    setBusy("execute");
    try {
      const result = await api.executeAction(active.action_id, token);
      const action = unwrapAction(result);
      setActive(action);
      setToken(null);
      await refresh(action.action_id);
      onNotify(`${money(action.amount_inr)} refund executed exactly once`);
      onAction?.();
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Execution failed");
    } finally {
      setBusy(null);
    }
  }

  const requiresReview = active?.status === "pending_review";
  const canExecute = active && Boolean(token) && !["executed", "rejected"].includes(active.status);

  return (
    <section className="gateway-section" id="action-gateway">
      <div className="section-heading gateway-heading">
        <div>
          <p className="eyebrow">Two-phase execution</p>
          <h2>Action Gateway</h2>
          <p className="section-copy">The model may propose a refund. Only ControlPlane can authorize and execute it.</p>
        </div>
        <div className="gateway-legend"><i /> System of record <span>→</span> Policy <span>→</span> Executor</div>
      </div>

      <div className="order-strip">
        {orders.map((order) => (
          <button key={order.order_id} className={`order-card ${orderId === order.order_id ? "selected" : ""}`} onClick={() => chooseOrder(order)}>
            <span className="order-card-top"><b>{order.order_id}</b><em>{order.refund_status ?? order.status}</em></span>
            <strong>{money(order.order_total_inr)}</strong>
            <span>{order.item}</span>
            <small>{order.fulfilment_issue?.replaceAll("_", " ") ?? "No reported issue"}</small>
          </button>
        ))}
      </div>

      <div className="gateway-grid">
        <article className="gateway-card proposal-card">
          <div className="card-number">01</div>
          <p className="kicker">Agent proposal</p>
          <h3>Request a governed refund</h3>
          <label>Order <input value={orderId} readOnly /></label>
          <label>Refund amount (INR)<input type="number" min="0" value={amount} onChange={(event) => setAmount(event.target.value)} /></label>
          <label>Reason<select value={reason} onChange={(event) => setReason(event.target.value)}>
            <option value="wrong_item">Wrong item delivered</option>
            <option value="damaged">Damaged goods</option>
            <option value="late_delivery">Late delivery</option>
            <option value="change_of_mind">Change of mind</option>
            <option value="suspected_fraud">Suspected fraud</option>
          </select></label>
          <button className="primary gateway-cta" disabled={!orderId || busy !== null} onClick={propose}>{busy === "propose" ? "Evaluating…" : "Propose action"}<span>→</span></button>
          <p className="form-note">Try changing the amount. The executor never trusts model-generated numbers.</p>
        </article>

        <article className="gateway-card decision-card">
          <div className="card-number">02</div>
          <p className="kicker">Policy checkpoint</p>
          <h3>{active ? "Decision receipt" : "Awaiting proposal"}</h3>
          {!active ? <div className="gateway-empty"><i /><p>Select an order and propose an action to generate an auditable decision.</p></div> : <>
            <div className="action-decision-row"><span className={`decision-badge ${active.decision}`}>{active.decision.replaceAll("_", " ")}</span><strong>{(active.risk_score ?? 0).toFixed(1)} risk</strong></div>
            <p className="action-summary">{active.decision_summary ?? `Policy returned ${active.decision.replaceAll("_", " ")} for this ${money(active.amount_inr)} refund.`}</p>
            <div className="receipt-grid"><span>Action ID<b>{active.action_id}</b></span><span>Status<b>{active.status.replaceAll("_", " ")}</b></span><span>Amount<b>{money(active.amount_inr)}</b></span><span>Policy<b>{active.policy_version ?? "active"}</b></span></div>
            <div className="reason-chips">{(active.reason_codes ?? []).map((code) => <span key={code}>{code}</span>)}</div>
          </>}
        </article>

        <article className="gateway-card execution-card">
          <div className="card-number">03</div>
          <p className="kicker">Controlled executor</p>
          <h3>{active?.status === "executed" ? "Refund completed" : requiresReview ? "Human checkpoint" : "Authorization gate"}</h3>
          {requiresReview ? <div className="review-form">
            <label>Verified amount (INR)<input type="number" value={reviewAmount} onChange={(event) => setReviewAmount(event.target.value)} /></label>
            <label>Reviewer note<textarea rows={3} value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} /></label>
            <div className="review-actions"><button className="secondary" disabled={busy !== null} onClick={() => review("approve")}>Correct & approve</button><button className="danger-button" disabled={busy !== null} onClick={() => review("reject")}>Reject</button></div>
          </div> : <div className={`executor-state ${active?.status === "executed" ? "success" : ""}`}>
            <span className="executor-icon">{active?.status === "executed" ? "✓" : token ? "↗" : "⌁"}</span>
            <p>{active?.status === "executed" ? `${money(active.amount_inr)} was written to the commerce ledger.` : token ? "A short-lived, amount-bound authorization is ready." : "No action can reach the commerce system without authorization."}</p>
          </div>}
          {!requiresReview && active?.status !== "executed" && <button className="primary gateway-cta" disabled={!canExecute || busy !== null} onClick={execute}>{busy === "execute" ? "Executing…" : "Execute authorized refund"}<span>→</span></button>}
          {active?.status === "executed" && <div className="immutable-note">Replay protected · Transaction committed · Receipt retained</div>}
        </article>
      </div>

      {actions.length > 0 && <div className="action-ledger"><span>Live action ledger</span>{actions.slice(0, 5).map((action) => <button key={action.action_id} onClick={() => { setActive(action); setToken(action.authorization_token ?? null); }}>{action.order_id}<b>{money(action.amount_inr)}</b><em className={action.status}>{action.status.replaceAll("_", " ")}</em></button>)}</div>}
    </section>
  );
}
