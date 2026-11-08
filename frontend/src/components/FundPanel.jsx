import { PayPalScriptProvider, PayPalButtons, usePayPalScriptReducer } from "@paypal/react-paypal-js";
import { api } from "../api.js";

// PayPal JS SDK (v5 buttons). intent=authorize: the server creates an Orders v2 order with
// intent AUTHORIZE, so funds are held on approval and only captured after verification.
// (The v6 SDK checkout session failed with genericError for AUTHORIZE orders in sandbox.)
function Buttons({ milestone, onFunded, onError }) {
  const [{ isPending, isRejected }] = usePayPalScriptReducer();
  if (isPending) return <div className="muted">Loading PayPal...</div>;
  if (isRejected) return <div className="alert alert-red">Failed to load the PayPal SDK. Check PAYPAL_CLIENT_ID.</div>;

  return (
    <div className="pay-buttons">
      <PayPalButtons
        style={{ layout: "vertical", shape: "rect", label: "pay" }}
        forceReRender={[milestone.id]}
        createOrder={async () => (await api.createOrder(milestone.id)).id}
        onApprove={async (data) => {
          await api.authorize(milestone.id, data.orderID);
          onFunded();
        }}
        onCancel={() => onError("Checkout cancelled.")}
        onError={(err) => onError(err?.message || "PayPal checkout error")}
      />
    </div>
  );
}

export default function FundPanel({ config, milestone, onFunded, onError }) {
  if (!config.paypal_configured) {
    return <div className="alert alert-amber">PayPal sandbox credentials are not configured on the server. Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env.</div>;
  }
  return (
    <PayPalScriptProvider options={{ clientId: config.paypal_client_id, currency: config.currency, intent: "authorize", enableFunding: "venmo" }}>
      <Buttons milestone={milestone} onFunded={onFunded} onError={onError} />
    </PayPalScriptProvider>
  );
}
