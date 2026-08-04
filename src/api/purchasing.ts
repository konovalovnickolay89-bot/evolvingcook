import { apiRequest } from "./client";
import type {
  BatchDeliveryLinesIn,
  CreateDeliveryIn,
  DeliveryOut,
  PurchaseOrderOut,
} from "./types";

export function getPurchaseOrder(
  poId: number,
  signal?: AbortSignal,
): Promise<PurchaseOrderOut> {
  return apiRequest<PurchaseOrderOut>(`/purchasing/orders/${poId}`, { signal });
}

export function sendPurchaseOrder(
  poId: number,
  signal?: AbortSignal,
): Promise<PurchaseOrderOut> {
  return apiRequest<PurchaseOrderOut>(`/purchasing/orders/${poId}/send`, {
    method: "POST",
    body: null,
    signal,
  });
}

export function createDelivery(
  poId: number,
  body: CreateDeliveryIn,
  signal?: AbortSignal,
): Promise<DeliveryOut> {
  return apiRequest<DeliveryOut>(`/purchasing/orders/${poId}/deliveries`, {
    method: "POST",
    body,
    signal,
  });
}

export function getDelivery(
  deliveryId: number,
  signal?: AbortSignal,
): Promise<DeliveryOut> {
  return apiRequest<DeliveryOut>(`/purchasing/deliveries/${deliveryId}`, {
    signal,
  });
}

export function batchDeliveryLines(
  deliveryId: number,
  body: BatchDeliveryLinesIn,
  signal?: AbortSignal,
): Promise<DeliveryOut> {
  return apiRequest<DeliveryOut>(
    `/purchasing/deliveries/${deliveryId}/lines/batch`,
    { method: "POST", body, signal },
  );
}
