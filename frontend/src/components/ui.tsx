import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "../lib/utils"

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("panel", className)} {...props} />
}

const badgeVariants = cva("badge", {
  variants: { tone: { green: "badge-green", amber: "badge-amber", red: "badge-red", blue: "badge-blue", neutral: "badge-neutral" } },
  defaultVariants: { tone: "neutral" },
})

export function Badge({ tone, className, children }: VariantProps<typeof badgeVariants> & { className?: string; children: ReactNode }) {
  return <span className={cn(badgeVariants({ tone }), className)}>{children}</span>
}

const buttonVariants = cva("button", {
  variants: { variant: { primary: "button-primary", ghost: "button-ghost" } },
  defaultVariants: { variant: "primary" },
})

export function Button({ variant, className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>) {
  return <button className={cn(buttonVariants({ variant }), className)} {...props} />
}
