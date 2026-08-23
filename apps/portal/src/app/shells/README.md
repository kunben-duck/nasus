# Portal Shells

Shells own persistent layout chrome only: top-level sidebar, project workspace navigation, settings popover anchoring, and shared page slots.

They must not contain product workflow logic. Route pages compose shells with domain view models and shared UI primitives.

## Shell Rules

- Shell views may own sidebar collapse state, settings popover anchoring, and persistent chrome.
- Shell containers may compose platform domain hooks with shared UI for account menus and settings panels.
- `*ShellView.tsx` files must not import `domains/*`; they receive account/settings slots and backend status from their container.
- Shells must not call product workflow mutations directly.
- Shells must not render route-specific cards, panels, or tool workflows.
