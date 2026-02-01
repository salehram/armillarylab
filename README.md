# AstroPlanner

A comprehensive web-based tool for planning astrophotography sessions and managing imaging targets. Built with Flask and designed to help astrophotographers optimize their imaging time and track their progress.

![Version](https://img.shields.io/badge/version-2.0.0-brightgreen.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.14+-green.svg)
![Flask](https://img.shields.io/badge/flask-3.0.3-red.svg)
![Status](https://img.shields.io/badge/status-stable-success.svg)

## 🎉 Version 2.0.0 - Database & Filter Management Release

AstroPlanner v2.0.0 brings major improvements for production deployment and equipment management, including PostgreSQL support, comprehensive filter management, target archiving, and enhanced dark theme visibility.

## 🌟 Features

### 📊 Target Management & Planning
- **Project-based Organization**: Each target is treated as its own imaging project with dedicated tracking
- **Creation Tracking**: Automatic timestamp tracking with local timezone support
- **Target Settings**: Per-target overrides for pack-up time and minimum altitude constraints
- **Priority Scoring**: Intelligent priority calculation based on completion percentage, remaining time, and tonight's window
- **Advanced Filter System**: Custom filter addition with real-time bidirectional calculations (minutes ↔ frames ↔ exposure time)
- **NINA Filter Mapping**: Custom filters map to standard telescope filter wheel names for hardware compatibility

### 🎯 Session Planning & Execution
- **Tonight's Recommendation**: AI-driven target recommendations for optimal session planning
- **Window Calculations**: Automatic calculation of imaging windows based on:
  - Sunset and astronomical darkness times
  - Target altitude constraints with visual chart indicators
  - Observer location and timezone with global configuration
- **Progress Tracking**: Comprehensive tracking with edit/delete functionality for session records
- **Time Management**: Flexible time input with H:M:S formatting and bidirectional conversions
- **Imaging Logs**: Complete session history with statistics, analytics, and backdating support

### 🎨 Palette & Filter Management
- **Custom Palettes**: Create and manage custom filter palettes with JSON-based storage
- **Database-driven CRUD**: Full palette management with system vs. custom palette protection
- **Filter Recommendations**: Smart filter recommendations based on target type and palette selection
- **Auto-populated Dropdowns**: Filter selection automatically populates from active target plans

### 📈 Advanced Planning & Calculations
- **Bidirectional Frame/Time Inputs**: Change frame counts to update exposure times and vice versa with decimal precision
- **Real-time Calculations**: Dynamic updates as you modify exposure plans with JavaScript validation
- **Status Indicators**: Visual badges showing completion status and tonight's imaging potential
- **Multi-format Time Display**: Times shown in both minutes and H:M:S format throughout the interface
- **Custom Filter Addition**: On-the-fly custom filter addition with auto-save and NINA compatibility

### 🔧 NINA Integration & Export
- **Export Compatibility**: Direct export to N.I.N.A. (Nighttime Imaging 'N' Astronomy) Advanced Sequencer
- **Template System**: Customizable sequence templates with dynamic block generation
- **Filter Wheel Integration**: Custom filter mapping ensures proper telescope hardware operation
- **Remaining Frames Export**: Intelligent export of only remaining frames for efficient session continuation
- **📚 Documentation**: See [NINA Integration Guide](docs/NINA_INTEGRATION.md) for detailed setup instructions

### 📤 AstroBin Integration
- **Per-Target CSV Export**: Export acquisition data in AstroBin-compatible CSV format
- **Filter ID Mapping**: Store AstroBin equipment database IDs for accurate data import
- **Configurable Export Settings**: Binning, gain, sensor cooling, and Bortle scale options
- **Smart Filter Mapping**: Automatic mapping from channel names to base filter IDs
- **📚 Documentation**: See [AstroBin Export Guide](docs/ASTROBIN_EXPORT.md) for complete workflow

### 🔄 Equipment Preset System
- **JSON-Based Presets**: Modular filter and equipment configuration files
- **Multi-User Support**: Easy sharing and import of filter configurations
- **Brand-Specific Presets**: Pre-configured presets for ZWO and other filter brands
- **CLI & Web Management**: Full preset management via command line and web interface
- **Export/Import**: Backup and restore equipment configurations
- **📚 Documentation**: See [Equipment Presets Guide](docs/PRESETS_GUIDE.md) for detailed usage

### 🌍 Global Configuration & Settings
- **Observer Location**: Configurable latitude, longitude, and elevation with global defaults
- **Timezone Support**: Robust timezone handling with Windows compatibility and UTC conversion
- **Default Settings**: Global defaults for pack-up time and minimum altitude with per-target overrides
- **Settings Management**: Dedicated configuration interface for both global and per-target settings

### 📊 Data Management & Analytics
- **Session Edit/Delete**: Complete CRUD operations for imaging session management with confirmation dialogs
- **Comprehensive Logs**: Imaging session tracking with date grouping, statistics, and monthly summaries
- **Progress Analytics**: Daily, monthly, and overall imaging statistics with visual indicators
- **Data Integrity**: Form validation, error handling, and database consistency maintenance

## 📚 Documentation

Detailed documentation is available in the [docs/](docs/) folder:

| Guide | Description |
|-------|-------------|
| [Palette & Filter Guide](docs/PALETTE_FILTER_GUIDE.md) | **Start here!** Understand palettes, filters, and target plans |
| [Equipment Presets Guide](docs/PRESETS_GUIDE.md) | Configure and share filter setups using JSON presets |
| [NINA Integration Guide](docs/NINA_INTEGRATION.md) | Export imaging sequences to N.I.N.A. |
| [AstroBin Export Guide](docs/ASTROBIN_EXPORT.md) | Export sessions as AstroBin-compatible CSV |
| [Database Guide](docs/DATABASE_GUIDE.md) | SQLite/PostgreSQL setup and migration |
| [Features Roadmap](docs/FEATURES_ROADMAP.md) | Completed features and future plans |

## �🚀 Quick Start

### Prerequisites

- Python 3.14+ (tested on 3.14.2)
- Git (for cloning the repository)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/astroplanner.git
   cd astroplanner
   ```

2. **Create and activate virtual environment**
   ```bash
   # Windows
   python -m venv dev
   dev\Scripts\activate

   # Linux/macOS
   python -m venv dev
   source dev/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Initialize the database**
   ```bash
   flask init-db
   ```

5. **Run the application**
   ```bash
   flask run
   ```

6. **Open your browser**
   Navigate to `http://127.0.0.1:5000`

## 🖥️ Command Line Interface (CLI)

AstroPlanner provides comprehensive CLI commands for database management, equipment configuration, and system administration.

### Database Commands

#### `flask init-db`
Initialize the database with configurable presets.

```bash
# Standard setup with generic filters
flask init-db

# Use ZWO filters with AstroBin IDs
flask init-db --filter-preset zwo

# Minimal setup (filters only, no palettes/wheels)
flask init-db --mode minimal

# Force re-initialization (clears existing data)
flask init-db --force

# Combined options
flask init-db --mode starter --filter-preset zwo --force
```

**Options:**
| Option | Values | Description |
|--------|--------|-------------|
| `--mode` | `starter`, `minimal` | `starter` = full setup with palettes/types/wheel; `minimal` = just filters |
| `-f, --filter-preset` | preset name | Filter preset to use (e.g., `generic`, `zwo`) |
| `--force` | flag | Force re-initialization, drops existing data |

#### `flask migrate-db`
Run database migrations for schema changes.

```bash
flask migrate-db
```

This command handles schema updates such as adding new columns to existing tables. Safe to run multiple times - only applies pending migrations.

### Equipment Preset Commands

#### `flask list-presets`
Display available filter presets with details.

```bash
flask list-presets
```

**Output includes:**
- Preset name and description
- Number of filters included
- Whether AstroBin IDs are configured

#### `flask export-preset`
Export current filters and optionally filter wheels to a JSON file.

```bash
# Export filters only
flask export-preset my_filters.json

# Export filters and filter wheel configuration
flask export-preset my_setup.json --include-wheels
```

**Options:**
| Option | Description |
|--------|-------------|
| `--include-wheels` | Include filter wheel configurations in export |

#### `flask import-preset`
Import filters from a JSON preset file.

```bash
# Replace existing filters with imported ones
flask import-preset my_filters.json

# Merge with existing filters (add new, update existing)
flask import-preset my_filters.json --merge

# Also import filter wheel configurations
flask import-preset my_setup.json --include-wheels
```

**Options:**
| Option | Description |
|--------|-------------|
| `--merge` | Merge with existing filters instead of replacing |
| `--include-wheels` | Also import filter wheel configurations |

### Database Administration Commands

#### `flask db info`
Display current database configuration and test connection.

```bash
flask db info
```

#### `flask db backup`
Create a backup of the current database.

```bash
flask db backup
```

#### `flask db reset`
Reset the database for development (use with caution).

```bash
flask db reset
```

### Running the Application

#### Development Server
```bash
# Default (port 5000)
flask run

# Custom port
flask run --port 5001

# Debug mode with auto-reload
flask run --debug

# Accessible from network
flask run --host 0.0.0.0
```

#### Production Server
```bash
# Using Gunicorn (recommended for production)
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FLASK_APP` | Application module | `app.py` |
| `FLASK_ENV` | Environment mode | `production` |
| `SECRET_KEY` | Flask secret key | `dev-secret-key` |
| `DATABASE_URL` | Database connection string | SQLite |
| `UPLOAD_FOLDER` | File upload directory | `./uploads` |

## 📋 Usage

### First-Time Setup

1. **Configure Global Settings**
   - Navigate to Settings (gear icon in navbar)
   - Set your observer location (latitude, longitude, elevation)
   - Configure default pack-up time and minimum altitude
   - Set your timezone

2. **Create Your First Target**
   - Click "+ New Target" on the home page
   - Enter target details (name, catalog ID, coordinates)
   - Set target type (Galaxy, Nebula, Star Cluster, etc.)
   - Choose or create a custom palette

3. **Plan Your Session**
   - Open the target detail page
   - Set total planned exposure time (in minutes or H:M:S format)
   - Configure channel-specific exposure plans
   - Use bidirectional frame/time inputs for precise planning

### Daily Workflow

1. **Check Tonight's Recommendation**
   - View the prioritized target recommendation on the home page
   - Review tonight's imaging window and suggested focus channel

2. **Update Progress**
   - Record completed exposures in the target detail page
   - Track progress with visual status indicators
   - Monitor remaining work and completion percentages

3. **Export to NINA**
   - Generate Advanced Sequencer files for remaining exposures
   - Automatic integration with your existing NINA templates

## 🗂️ Project Structure

```
astroplanner/
├── app.py                 # Main Flask application
├── astro_utils.py         # Astronomical calculations
├── cli.py                 # CLI command definitions
├── nina_integration.py    # N.I.N.A. export functionality
├── time_utils.py          # Time formatting and parsing utilities
├── requirements.txt       # Python dependencies
├── .flaskenv              # Flask server settings (auto-loaded)
├── .env.example           # Environment template for development
├── .env.production        # Environment template for production
├── DATABASE_GUIDE.md      # Database setup and migration guide
├── FEATURES_ROADMAP.md    # Feature development roadmap
├── config/                # Configuration modules
│   ├── database.py        # Database configuration
│   ├── migration.py       # Migration utilities
│   └── presets/           # Equipment preset files
│       ├── base.json      # Palettes, target types, wheel config
│       └── filters/       # Filter preset files
│           ├── generic.json   # Generic filters (no AstroBin IDs)
│           └── zwo.json       # ZWO filters with AstroBin IDs
├── templates/             # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── target_detail.html
│   ├── target_form.html
│   ├── settings.html
│   ├── filter_form.html
│   ├── filter_list.html
│   ├── filter_wheel_form.html
│   ├── filter_wheel_list.html
│   ├── palette_list.html
│   └── imaging_logs.html
├── static/                # Static assets (CSS, JS, fonts)
├── dev/                   # Virtual environment
├── uploads/               # File uploads directory
└── astroplanner.db        # SQLite database (created after init)
```

## ⚙️ Configuration

### Configuration Files

AstroPlanner uses several configuration files for different environments:

| File | Purpose | Auto-loaded |
|------|---------|-------------|
| `.flaskenv` | Flask server settings (host, port, debug mode) | ✅ Yes (by Flask) |
| `.env` | Your local environment settings (create from `.env.example`) | ✅ Yes (with python-dotenv) |
| `.env.example` | Template for development settings | ❌ No (reference only) |
| `.env.production` | Template for production deployment | ❌ No (reference only) |

#### `.flaskenv` - Flask Server Settings

This file is **auto-loaded by Flask** and controls how the development server runs:

```dotenv
FLASK_APP=app.py
FLASK_RUN_HOST=0.0.0.0
FLASK_RUN_PORT=5000
FLASK_ENV=development
FLASK_DEBUG=True
```

#### `.env.example` - Development Template

Copy this file to `.env` for local development:

```bash
# Windows
copy .env.example .env

# Linux/macOS
cp .env.example .env
```

Then edit `.env` with your settings (database, secret key, etc.).

#### `.env.production` - Production Template

Use this as a reference when deploying to production. Contains:
- PostgreSQL configuration
- Security settings (SSL, secure cookies)
- Production-appropriate pool sizes

> ⚠️ **Never commit `.env` files with real credentials to version control!**

For detailed database configuration using these files, see [DATABASE_GUIDE.md](DATABASE_GUIDE.md).

### Environment Variables

- `SECRET_KEY`: Flask secret key (defaults to 'dev-secret-key')
- `DATABASE_URL`: Database connection string (defaults to SQLite)
- `DATABASE_TYPE`: Database type - `sqlite` or `postgresql` (defaults to SQLite)
- `UPLOAD_FOLDER`: File upload directory (defaults to ./uploads)
- `OBSERVER_TZ`: Observer timezone (defaults to UTC+3)

### Equipment Presets

AstroPlanner supports JSON-based equipment presets for easy configuration sharing:

**Creating Custom Presets:**
1. Export your current configuration: `flask export-preset my_filters.json --include-wheels`
2. Edit the JSON file to customize filter names, AstroBin IDs, etc.
3. Place in `config/presets/filters/` for automatic detection
4. Use with: `flask init-db --filter-preset my_filters`

**Preset File Format:**
```json
{
  "preset_name": "My Custom Filters",
  "description": "Description of filter set",
  "filters": [
    {
      "name": "H",
      "display_name": "Hydrogen Alpha",
      "filter_type": "narrowband",
      "default_exposure": 300,
      "astrobin_id": 1955
    }
  ]
}
```

**AstroBin Filter IDs:**
Find your filter IDs from AstroBin equipment URLs:
- `https://www.astrobin.com/equipment/filter/1955/` → ID is `1955`

### Database Models

The application uses SQLAlchemy ORM with support for SQLite and PostgreSQL:

- **GlobalConfig**: Observer location, default settings, timezone
- **TargetType**: Target classification system
- **Palette**: Custom filter palette definitions
- **Target**: Individual imaging targets
- **TargetPlan**: Exposure plans and channel definitions
- **ImagingSession**: Session tracking and progress data
- **Filter**: Filter definitions with AstroBin IDs
- **FilterWheel**: Filter wheel hardware profiles
- **FilterWheelSlot**: Filter-to-slot position mappings
- **ObjectMapping**: Catalog cross-references

## 🐳 Docker Support

The project includes Docker configuration for containerized deployment:

```bash
# Build and run with Docker Compose
docker-compose up --build
```

## 🛠️ Development

### Dependencies

- **Flask 3.0.3**: Web framework
- **SQLAlchemy 2.0.32**: Database ORM
- **Astropy ≥7.2.0**: Astronomical calculations
- **Astroplan ≥0.10.1**: Observation planning
- **NumPy ≥2.3.5**: Numerical computations

### Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📊 Current Status

### ✅ Completed Features (v2.0.0)

**Core Functionality:**
- Target-as-project design with creation timestamps
- Local timezone support with Windows compatibility
- Database rebuild support with CLI commands
- NINA export functionality for remaining exposures
- Global and per-target configuration management
- Palette management system with CRUD operations
- Plan & Palette Enhancements with H:M:S formatting
- Bidirectional frame/time input functionality
- Altitude Chart with moon position, meridian flip, current time markers
- Comprehensive imaging logs and session tracking

**New in v2.0.0:**
- 🗄️ **PostgreSQL Support**: Full production database support with automatic migration
- 🎛️ **Filter Management System**: Complete filter and filter wheel configuration
- 📦 **Target Archiving**: Archive completed targets to keep workspace clean
- 🔗 **Object Mapping**: Cross-reference catalogs with AstroBin integration
- ⚙️ **Equipment Preset System**: JSON-based configuration sharing
- 📤 **AstroBin CSV Export**: Filter ID mapping for seamless uploads
- 👥 **Multi-user Setup Support**: Import/export presets for team use
- 🎨 **Dark Theme UI Improvements**: Better visibility across all pages

### 🚧 Roadmap

- **Session Recommendation Engine**: AI-driven session optimization
- **Automatic Recomputation**: Dynamic updates after configuration changes
- **Advanced Export Options**: Additional template formats and customization
- **Comprehensive User Guide**: Documentation and tutorials

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with the assistance of AI for rapid development
- Astropy and Astroplan communities for excellent astronomical libraries
- N.I.N.A. project for advanced sequencer integration
- Flask and SQLAlchemy communities for robust web framework foundation

## 📞 Support

For questions, issues, or feature requests:

1. Browse the [docs/](docs/) folder for detailed guides
2. Check the [Features Roadmap](docs/FEATURES_ROADMAP.md) for planned development
3. Open an issue on GitHub
4. Review existing documentation and code comments

---

**Happy Imaging! 🌌✨**
