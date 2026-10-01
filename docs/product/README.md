# Product Docs

- [UI design principles](./ui-design-principles.md)
- [Core platform user acceptance](./core-platform-user-acceptance.md)
- [Korean holidays](./korean-holidays.md)

Keep only implemented product-wide rules here. App-specific behavior belongs in `docs/apps/<app-id>/`.

## Brand

The shared product name and wordmark are **miy** (Make It Yourself).
Package names use `miy` / `@miy/*`; typed configuration uses `MIY_*` / `VITE_MIY_*`.
The brand never embeds a domain. Deployment origins, login redirects and download
addresses remain configuration, so acquiring a domain does not require renaming packages.
