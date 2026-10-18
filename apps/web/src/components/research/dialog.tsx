"use client";

import type { ReactNode } from "react";
import { Heading as AriaHeading } from "react-aria-components";
import { CloseButton } from "@/components/base/buttons/close-button";
import { Dialog, Modal, ModalOverlay } from "@/components/application/modals/modal";

interface Props {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    title: string;
    description?: ReactNode;
    children: ReactNode;
    footer?: ReactNode;
    size?: "md" | "lg";
}

/** Accessible modal built from the free Untitled UI modal primitives (focus trapped, Escape closes). */
export function DialogShell({ isOpen, onOpenChange, title, description, children, footer, size = "md" }: Props) {
    return (
        <ModalOverlay isOpen={isOpen} onOpenChange={onOpenChange} isDismissable>
            <Modal className={size === "lg" ? "max-w-3xl" : "max-w-xl"}>
                <Dialog aria-label={title}>
                    <div className="flex flex-col gap-5 p-6">
                        <div className="flex items-start gap-4">
                            <div className="flex flex-1 flex-col gap-1">
                                <AriaHeading slot="title" className="font-display text-lg font-semibold text-primary">
                                    {title}
                                </AriaHeading>
                                {description && <div className="text-sm text-tertiary">{description}</div>}
                            </div>
                            <CloseButton onPress={() => onOpenChange(false)} label="Close dialog" />
                        </div>
                        {children}
                        {footer && <div className="flex flex-wrap justify-end gap-3">{footer}</div>}
                    </div>
                </Dialog>
            </Modal>
        </ModalOverlay>
    );
}
