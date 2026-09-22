import React, { useState } from "react";
import { AlertTriangle, Info, X } from "lucide-react";

/** Styled system modal replacing native window.confirm / window.alert. */
const ConfirmModal = ({ title, message, confirmLabel, danger, onConfirm, onCancel }) => (
  <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/50 p-4" onClick={onCancel}>
    <div
      className="bg-white rounded-xl shadow-2xl max-w-md w-full overflow-hidden"
      onClick={(e) => e.stopPropagation()}
    >
      <div className={"px-5 py-4 flex items-center gap-3 " + (danger ? "bg-red-50" : "bg-blue-50")}>
        {danger
          ? <AlertTriangle className="w-5 h-5 text-red-600 flex-shrink-0" />
          : <Info className="w-5 h-5 text-blue-600 flex-shrink-0" />}
        <h3 className="font-bold text-gray-800">{title}</h3>
        <button onClick={onCancel} className="ml-auto text-gray-400 hover:text-gray-700">
          <X className="w-4 h-4" />
        </button>
      </div>
      <p className="px-5 py-4 text-sm text-gray-600 whitespace-pre-line">{message}</p>
      <div className="px-5 py-3 bg-gray-50 flex justify-end gap-2">
        <button
          onClick={onCancel}
          className="px-4 py-2 bg-white border border-gray-300 text-gray-700 hover:bg-gray-100 rounded-md text-sm font-medium transition-colors shadow-sm"
        >
          Cancel
        </button>
        <button
          onClick={onConfirm}
          className={"px-4 py-2 rounded-md text-sm font-medium transition-colors shadow-sm text-white " + (danger ? "bg-red-600 hover:bg-red-700" : "bg-blue-600 hover:bg-blue-700")}
        >
          {confirmLabel || "Confirm"}
        </button>
      </div>
    </div>
  </div>
);

/**
 * Hook: const [askConfirm, confirmModal] = useConfirm();
 * askConfirm({ title, message, confirmLabel, danger, onConfirm }) opens it;
 * render {confirmModal} once inside the page root.
 */
export const useConfirm = () => {
  const [state, setState] = useState(null);
  const ask = (opts) => setState(opts);
  const modal = state ? (
    <ConfirmModal
      title={state.title}
      message={state.message}
      confirmLabel={state.confirmLabel}
      danger={state.danger}
      onCancel={() => setState(null)}
      onConfirm={() => {
        const fn = state.onConfirm;
        setState(null);
        if (fn) fn();
      }}
    />
  ) : null;
  return [ask, modal];
};

export default ConfirmModal;
