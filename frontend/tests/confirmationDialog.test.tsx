import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDiscardDialog } from "../src/components/ConfirmDiscardDialog";

const title = "Potvrdite: Zatraži izmene";
const hash = "abcdef0123456789".repeat(4);
const reason = "Z".repeat(2000);
const message = `Verzija 27, očekivana revizija 83. SHA-256: ${hash} · Obrazloženje: ${reason}. Odluku će proveriti server.`;

function show(overrides = {}) {
  const onCancel = vi.fn(), onConfirm = vi.fn();
  return { ...render(<ConfirmDiscardDialog title={title} message={message} confirmLabel="Potvrdi odluku" cancelLabel="Odustani" onCancel={onCancel} onConfirm={onConfirm} {...overrides} />), onCancel, onConfirm };
}

describe("shared confirmation dialog", () => {
  it("preserves complete consequential text and accessible labels without truncation", () => {
    show({ lang: "sr-Latn" });
    const dialog = screen.getByRole("alertdialog", { name: title });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.getAttribute("lang")).toBe("sr-Latn");
    expect(document.getElementById(dialog.getAttribute("aria-describedby")!)?.textContent).toBe(message);
    expect(screen.getByRole("region", { name: title }).tabIndex).toBe(0);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Odustani" }));
  });

  it("keeps newlines, URLs and unbroken input exactly as supplied", () => {
    const exact = `Prvi red\r\nDrugi red\n\t${hash}\nhttps://example.test/${"x".repeat(2000)}`;
    show({ message: exact });
    const dialog = screen.getByRole("alertdialog");
    expect(document.getElementById(dialog.getAttribute("aria-describedby")!)?.textContent).toBe(exact);
  });

  it("keeps cancellation and confirmation separate", () => {
    const { onCancel, onConfirm } = show();
    fireEvent.click(screen.getByRole("button", { name: "Odustani" }));
    expect(onCancel).toHaveBeenCalledTimes(1); expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Potvrdi odluku" }));
    expect(onConfirm).toHaveBeenCalledTimes(1); expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("includes the keyboard-scrollable message in the focus trap and handles Escape there", () => {
    const { onCancel, onConfirm } = show();
    const region = screen.getByRole("region"), confirm = screen.getByRole("button", { name: "Potvrdi odluku" });
    confirm.focus(); fireEvent.keyDown(confirm, { key: "Tab" }); expect(document.activeElement).toBe(region);
    fireEvent.keyDown(region, { key: "Tab", shiftKey: true }); expect(document.activeElement).toBe(confirm);
    region.focus(); fireEvent.keyDown(region, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1); expect(onConfirm).not.toHaveBeenCalled();
  });

  it("preserves existing discard labels, callbacks and focus restoration", () => {
    const trigger = document.createElement("button"); document.body.append(trigger); trigger.focus();
    const { unmount, onCancel, onConfirm } = show({ cancelLabel: undefined, confirmLabel: "Discard and leave", title: "Leave unsaved editorial changes?" });
    expect(screen.getByRole("button", { name: "Keep editing" })).toBe(document.activeElement);
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1); expect(onConfirm).not.toHaveBeenCalled();
    unmount(); expect(document.activeElement).toBe(trigger); trigger.remove();
  });

  it("follows reduced/panned visual viewports and removes its listeners on close", () => {
    const visible = Object.assign(new EventTarget(), { width: 390, height: 300, offsetLeft: 0, offsetTop: 40 });
    const remove = vi.spyOn(visible, "removeEventListener"); vi.stubGlobal("visualViewport", visible);
    const { unmount } = show(); const overlay = screen.getByRole("alertdialog").parentElement!;
    expect(overlay.style.height).toBe("300px"); expect(overlay.style.top).toBe("40px");
    act(() => { visible.width = 320; visible.height = 240; visible.offsetTop = 60; visible.offsetLeft = 5; visible.dispatchEvent(new Event("resize")); });
    expect(overlay.style.height).toBe("240px"); expect(overlay.style.width).toBe("320px");
    act(() => { visible.dispatchEvent(new Event("scroll")); });
    expect(overlay.style.top).toBe("60px"); expect(overlay.style.left).toBe("5px");
    unmount(); expect(remove.mock.calls.map(([name]) => name)).toEqual(["resize", "scroll"]);
  });
});
