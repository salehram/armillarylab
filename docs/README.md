# AstroPlanner Documentation

Welcome to the AstroPlanner documentation. This folder contains detailed guides for various features and deployment scenarios.

---

## 📚 Documentation Index

### Getting Started

| Document | Description |
|----------|-------------|
| [README.md](../README.md) | Project overview, installation, and quick start |
| [CHANGELOG.md](../CHANGELOG.md) | Version history and release notes |

### User Guides

| Document | Description |
|----------|-------------|
| [Palette & Filter Guide](PALETTE_FILTER_GUIDE.md) | **Start here!** Understand palettes, filters, and target plans |
| [Equipment Presets Guide](PRESETS_GUIDE.md) | Configure and share filter setups using JSON presets |
| [NINA Integration Guide](NINA_INTEGRATION.md) | Export imaging sequences to N.I.N.A. |
| [AstroBin Export Guide](ASTROBIN_EXPORT.md) | Export sessions as AstroBin-compatible CSV |

### Database & Deployment

| Document | Description |
|----------|-------------|
| [Database Guide](DATABASE_GUIDE.md) | SQLite/PostgreSQL setup and migration |
| [PostgreSQL Deployment](POSTGRESQL_DEPLOYMENT.md) | Production PostgreSQL configuration |
| [PostgreSQL Summary](POSTGRESQL_SUMMARY.md) | Quick reference for PostgreSQL features |
| [Deployment Security Plan](DEPLOYMENT_SECURITY_PLAN.md) | Security considerations for deployment |

### Development

| Document | Description |
|----------|-------------|
| [Features Roadmap](FEATURES_ROADMAP.md) | Completed features and future plans |
| [Third-Party Licenses](THIRD_PARTY_LICENSES.md) | Licenses for dependencies |

---

## 🔗 Quick Links

### Common Tasks

- **Initial Setup**: Start with the [README](../README.md), then [Database Guide](DATABASE_GUIDE.md)
- **Configure Filters**: See [Equipment Presets Guide](PRESETS_GUIDE.md)
- **Export to NINA**: See [NINA Integration Guide](NINA_INTEGRATION.md)
- **Upload to AstroBin**: See [AstroBin Export Guide](ASTROBIN_EXPORT.md)
- **Deploy to Cloud**: See [PostgreSQL Deployment](POSTGRESQL_DEPLOYMENT.md)

### CLI Commands Quick Reference

```powershell
# Database
flask init-db                              # Initialize database
flask db info                              # Show current database
flask db migrate --to postgresql           # Migrate to PostgreSQL
flask db backup                            # Create backup

# Presets
flask list-presets                         # List available presets
flask export-preset output.json            # Export current config
flask import-preset input.json             # Import preset

# Filters
flask init-db --filter-preset zwo          # Init with ZWO filters
```

---

## 📝 Contributing to Documentation

If you find errors or want to improve the documentation:

1. Fork the repository
2. Edit the relevant Markdown file in `docs/`
3. Submit a Pull Request

### Documentation Style

- Use clear, concise language
- Include practical examples
- Add troubleshooting sections
- Keep formatting consistent with existing docs

---

## 📞 Support

- Check the [Features Roadmap](FEATURES_ROADMAP.md) for planned improvements
- Open an issue on GitHub for bugs or feature requests
- Review existing documentation before asking questions
