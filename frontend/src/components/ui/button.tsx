import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded-xl text-sm font-semibold transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#34518f] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-[#f5c518] text-[#0b1f4d] shadow-[0_12px_24px_-16px_rgba(11,31,77,0.8)] hover:bg-[#e5b300]",
        secondary: "border border-[#d8e1ef] bg-white text-[#0b1f4d] hover:bg-[#f5f8fd]",
        accent: "bg-[#0b1f4d] text-white hover:bg-[#10295f]"
      },
      size: {
        default: "h-10 px-4 py-2",
        lg: "h-14 px-8 text-base",
        sm: "h-9 rounded-md px-3"
      }
    },
    defaultVariants: {
      variant: "default",
      size: "default"
    }
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
  }
);

Button.displayName = "Button";

export { Button, buttonVariants };
