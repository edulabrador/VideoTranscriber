import { useState } from "react";

import { postJson } from "../api/client";
import { useJobContext } from "../context/JobContext";
import { Icon } from "./Icon";

export function CancelButton() {
  const { state, dispatch } = useJobContext();
  const [cancelling, setCancelling] = useState(false);

  const handleCancel = async () => {
    if (!state.jobId) return;
    setCancelling(true);
    try {
      await postJson(`/api/jobs/${state.jobId}/cancel`, {});
    } catch (error) {
      setCancelling(false);
      dispatch({
        type: "CONNECTION_ERROR",
        message:
          error instanceof Error
            ? error.message
            : "No se pudo cancelar. Puedes intentarlo de nuevo.",
      });
    }
  };

  return (
    <button
      type="button"
      onClick={handleCancel}
      disabled={cancelling}
      className="secondary-button"
    >
      <Icon name="close" size={12} />
      {cancelling ? "Cancelando..." : "Cancelar"}
    </button>
  );
}
