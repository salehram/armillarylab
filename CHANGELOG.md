# Changelog

All notable changes to ArmillaryLab will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Project rename**: Versions 1.0.0 and 2.0.0 shipped under the previous project name **AstroPlanner**. The project was renamed to **ArmillaryLab** in 2026 to avoid conflict with an unrelated existing product. Historical version labels in this file refer to the project's name at the time of release.

## [2.1.0] - 2026-05-16

### 🎉 Version 2.1.0 - Night Conditions & Intelligent Channel Suggestion

**ArmillaryLab v2.1.0** adds real-time night conditions awareness with moon phase tracking, weather and astronomical seeing integration, and an intelligent channel suggestion engine -- all accessible from a single navbar icon.

### Changed

- Renamed the project from **AstroPlanner** to **ArmillaryLab** across code, config, Docker, documentation, and the SQLite database file (`astroplanner.db` to `armillarylab.db`).
- Updated default PostgreSQL DB name and role to `armillarylab` in [config/database.py](../config/database.py); existing PG deployments can keep using their current names by setting `DATABASE_URL` explicitly.
- Updated Docker Compose service/container names and PostgreSQL service defaults.
- Updated the GitHub repository URL references in `README.md`.

### Added

#### Night Conditions Popup
- **Moon phase overlay**: Current moon phase with emoji, illumination percentage, and next full moon countdown — computed offline via astroplan
- **Weather integration**: Temperature, humidity, cloud cover, and wind data from Open-Meteo API (free, no key required)
- **Astronomical seeing**: Seeing quality and transparency ratings from 7Timer API (free, no key required)
- **Channel suggestion engine**: Weighted scoring algorithm recommending the best filter channel based on moon suitability and remaining plan progress
  - `score = moon_weight * remaining_ratio` — Ha strongest (1.0 at full moon), OIII weakest (0.3), broadband (0.2)
- **Imaging window forecast**: Two-column layout showing current conditions alongside aggregated imaging window weather and seeing
- **3-tier offline fallback**: Online → cached 5-day forecast → offline moon-only → status message
- **Gmail-style navbar popup**: Dark-themed overlay card with Live/Cached/Offline status badge
- **Target-aware**: Shows channel suggestion when viewing a target, general conditions on other pages

#### New Files
- `conditions_utils.py` — Moon computation, weather/seeing API clients, caching, and channel scoring logic

### Notes

- No data migration required; the SQLite file rename preserves all data unchanged.
- No new Python dependencies — uses existing astropy/astroplan + stdlib urllib
- The GitHub redirect from the old repo URL keeps existing remotes working until they are updated with `git remote set-url`.

## [2.0.0] - 2026-02-01

### 🎉 Version 2.0.0 - PostgreSQL Support & Equipment Management

**AstroPlanner v2.0.0** (released under the project's previous name) is a major release introducing PostgreSQL database support for production deployments, comprehensive filter and filter wheel management, target archiving, and enhanced astronomy chart features.

### ✨ Major New Features

#### PostgreSQL Database Support
- **Dual Database Engine**: Runtime selection between SQLite (development) and PostgreSQL (production)
- **Automated Migration Tool**: Seamless bidirectional data migration between SQLite ↔ PostgreSQL
- **Connection Pooling**: Optimized PostgreSQL connection pooling for production workloads
- **Cloud-Ready**: Designed for deployment on Heroku, Railway, Render, and other cloud platforms
- **Environment Configuration**: Flexible `.env` file based configuration with sensible defaults

#### Filter & Filter Wheel Management
- **Filter Database**: Comprehensive filter management with types (narrowband, broadband, other)
- **Filter Wheels**: Multi-wheel support with slot configuration and NINA profile mapping
- **AstroBin Integration**: Filter AstroBin IDs for equipment CSV export compatibility
- **Bulk Updates**: Apply filter presets (generic, ZWO) with automatic AstroBin ID population

#### Target Archive System
- **Archive Completed Targets**: Mark finished projects as complete with notes
- **Clone Targets**: Duplicate archived targets to start new imaging projects
- **Archive View**: Separate view for completed/archived targets with restoration capability
- **Completion Tracking**: Record completion date and notes for project history

#### Enhanced Astronomy Charts
- **Moon Altitude Curve**: Visualize moon altitude alongside target altitude
- **Moon Rise/Set Indicators**: Clear markers showing moon visibility windows
- **Meridian Flip Marker**: Visual indicator for German Equatorial Mount flip timing
- **Improved Legend**: Better chart organization and readability

### 🔧 Improvements

#### Database Management CLI
- `flask db info` - Display current database configuration and status
- `flask db migrate` - Automated migration with 5-step workflow:
  1. Test target connection
  2. Initialize target schema
  3. Clear target data (with confirmation)
  4. Migrate all data
  5. Update `.env` file automatically
- `flask db backup` - Create timestamped database backups
- `flask init-db --force` - Clean database re-initialization

#### UI/UX Improvements
- **Fixed Text Visibility**: Page subtitles now use `text-info` for better dark theme visibility
- **Button Contrast**: Edit buttons use `btn-outline-secondary` for consistent visibility
- **Archived Targets Section**: Clear visual separation with improved button styling

#### Documentation
- **DATABASE_GUIDE.md**: Comprehensive guide for SQLite and PostgreSQL setup
- **DEPLOYMENT_SECURITY_PLAN.md**: Security considerations for production deployment
- **POSTGRESQL_DEPLOYMENT.md**: Step-by-step cloud deployment guide
- **Updated README**: Added configuration file documentation

### 🐛 Bug Fixes

- Fixed SQLAlchemy 2.0 count query syntax in migration tool
- Fixed `init-db --force` to properly drop all tables before recreation
- Fixed filter wheel edit button visibility (btn-outline-light → btn-outline-secondary)
- Fixed migration schema validation to check table existence
- Fixed test imports to match actual module API

### 📋 Technical Details

#### New Dependencies
- `psycopg2-binary` - PostgreSQL adapter for Python
- `python-dotenv` - Environment file management (already included)

#### Database Schema Changes
- Added `is_archived`, `archived_at`, `completion_notes` columns to targets table
- Added `astrobin_id` column to filters table
- New tables: `filter_wheels`, `filter_wheel_slots`, `palette_filters`

#### Configuration Files
- `.env.example` - Template for development configuration
- `.env.production` - Template for production PostgreSQL configuration
- `.flaskenv` - Flask server settings (auto-loaded)

### 📝 Migration from v1.0.0

1. **Backup your database**: `flask db backup`
2. **Update dependencies**: `pip install -r requirements.txt`
3. **Initialize new schema**: `flask init-db` (preserves existing data for SQLite)
4. **Optional PostgreSQL migration**: See DATABASE_GUIDE.md

### 🔒 License Change

- Changed from Apache 2.0 to MIT License for broader compatibility

---

## [1.0.0] - 2025-12-27

### 🎉 Version 1.0.0 - Complete Feature Set Release

**AstroPlanner v1.0.0** (released under the project's previous name) represents a mature, feature-complete astrophotography planning platform with comprehensive target management, session tracking, telescope integration, and advanced progress management capabilities.

### ✅ Complete Feature Set

#### Target Management & Planning
- **Project-based Organization**: Each target treated as its own imaging project with dedicated tracking
- **Creation Tracking**: Automatic timestamp tracking with robust local timezone support  
- **Target Settings**: Per-target overrides for pack-up time and minimum altitude constraints
- **Priority Scoring**: Intelligent priority calculation based on completion percentage, remaining time, and tonight's window
- **Advanced Filter System**: Custom filter addition with real-time bidirectional calculations (minutes ↔ frames ↔ exposure time)
- **NINA Filter Mapping**: Custom filters map to standard telescope filter wheel names for hardware compatibility

#### Session Planning & Execution
- **Tonight's Recommendation**: AI-driven target recommendations with intelligent priority scoring
- **Window Calculations**: Automatic imaging window calculation based on sunset, astronomical darkness, and altitude constraints
- **Enhanced Progress Tracking**: Comprehensive session tracking with edit/delete functionality and data validation
- **Advanced Time Management**: Flexible H:M:S formatting with bidirectional conversions and decimal precision support
- **Imaging Logs**: Complete session history with statistics, analytics, monthly summaries, and backdating support

#### Palette & Filter Management
- **Database-driven Palettes**: Full CRUD operations with system vs. custom palette protection and JSON-based storage
- **Auto-populated Filters**: Filter selection automatically populates from active target plans with custom filter support
- **Smart Filter Recommendations**: Intelligent filter suggestions based on target type and palette selection
- **Custom Filter Integration**: On-the-fly custom filter addition with auto-save and NINA telescope compatibility

#### Advanced Planning & Calculations  
- **Real-time Bidirectional Inputs**: Frame counts ↔ exposure times ↔ total minutes with decimal precision support
- **Dynamic Calculations**: Real-time JavaScript validation and calculation updates as you modify exposure plans
- **Multi-format Display**: Times displayed in both minutes and H:M:S format throughout the interface
- **Status Indicators**: Visual badges and progress indicators showing completion status and tonight's imaging potential
- **Column Organization**: Logical table column ordering for improved workflow efficiency

#### NINA Integration & Telescope Support
- **Advanced Export System**: Direct export to N.I.N.A. (Nighttime Imaging 'N' Astronomy) Advanced Sequencer
- **Filter Wheel Integration**: Custom filter mapping ensures proper telescope hardware operation and compatibility
- **Template System**: Customizable sequence templates with dynamic block generation
- **Remaining Frames Export**: Intelligent export of only remaining frames for efficient session continuation
- **Hardware Compatibility**: Full support for telescope filter wheels, cameras, and automation systems

#### Configuration & Global Settings
- **Observer Location**: Configurable latitude, longitude, and elevation with global defaults and validation
- **Timezone Support**: Robust timezone handling with Windows compatibility and automatic UTC conversion
- **Settings Management**: Dedicated configuration interface for both global and per-target settings
- **Default Overrides**: Global defaults with per-target override capabilities for flexible configuration

#### Data Management & Session Analytics
- **Session CRUD Operations**: Complete edit and delete functionality for imaging sessions with confirmation dialogs
- **Comprehensive Analytics**: Daily, monthly, and overall imaging statistics with visual progress indicators
- **Session History**: Complete imaging session tracking with date grouping and chronological organization
- **Data Integrity**: Form validation, error handling, UTF-8 encoding, and database consistency maintenance
- **Progress Visualization**: Charts, summaries, and visual indicators for session tracking and planning

#### Technical Excellence
- **Bootstrap Integration**: Fresh Bootstrap 5.3.2 and Bootstrap Icons 1.11.3 with proper asset integrity
- **Responsive Design**: Mobile-friendly interface with collapsible sections and space-efficient design
- **Form Validation**: HTML5 validation with JavaScript enhancement and selective auto-save functionality
- **Error Handling**: Comprehensive error handling with proper encoding and robust template management
- **Database Architecture**: SQLAlchemy-based models with JSON storage and efficient relationship management

### 🔧 Technical Improvements
- **Filter Recommendations**: Smart filter recommendations based on target type

#### Time Management & Planning
- **H:M:S Time Formatting**: Flexible time input and display in both minutes and H:M:S format
- **Bidirectional Frame/Time Inputs**: Change frame counts to update exposure times and vice versa
- **Real-time Calculations**: Dynamic updates as you modify exposure plans
- **Multi-format Display**: Times shown in both minutes and H:M:S throughout the interface

- **Fresh Bootstrap Assets**: Updated to Bootstrap 5.3.2 and Bootstrap Icons 1.11.3 with proper asset integrity
- **JavaScript Error Resolution**: Fixed Bootstrap JavaScript corruption and undefined reference errors
- **Template Encoding**: Proper UTF-8 encoding for all templates with comprehensive error handling
- **Database Model Updates**: Enhanced models for session editing and custom filter support
- **Route Architecture**: New `/session/<id>/edit` and `/session/<id>/delete` routes with proper validation

### 🔄 Migration from Previous Versions
- **Database Compatibility**: Maintains backward compatibility with existing data
- **Asset Updates**: Fresh Bootstrap assets resolve display issues and JavaScript errors
- **Template Updates**: Enhanced templates with improved encoding and functionality
- **Configuration Preservation**: All existing settings and data remain intact

### 🎯 Future Development

Version 1.0.0 establishes the foundation for future enhancements:
- **PostgreSQL Support**: Planned for v2.0 to enable cloud deployment capabilities
- **AI Session Recommendations**: Weather integration and machine learning-driven session optimization
- **Mobile Optimization**: Enhanced mobile interface for field use
- **Additional Observatory Integrations**: Support for more telescope control software

### 📝 Documentation

- **Complete Feature Roadmap**: Comprehensive documentation of all implemented features
- **Updated README**: Detailed feature list and quick start guide
- **Version Tracking**: Proper semantic versioning with VERSION file
- **Change Documentation**: Complete changelog with feature details and technical improvements

---

## Previous Development History

### Core Foundation (December 2025)
- **Target Management System**: Project-based target organization with creation tracking
- **Session Planning**: Tonight's recommendations with window calculations  
- **Palette Management**: Database-driven custom palette system
- **NINA Integration**: Advanced Sequencer export with template support
- **Global Configuration**: Observer location and settings management
- **Altitude Charts**: Visual planning tools with threshold indicators and window shading
- **Progress Tracking**: Comprehensive imaging session logging with statistics
- **Custom Filter System**: Real-time calculations with NINA mapping support

### Technical Foundation
- **Flask Architecture**: Modern Python web framework with SQLAlchemy ORM
- **Astronomical Computing**: Astropy and Astroplan integration for professional calculations
- **Database Design**: Comprehensive models with foreign key relationships and data integrity
- **Responsive UI**: Bootstrap-based interface optimized for desktop planning workflows
- **Windows Compatibility**: Robust timezone handling and path management

#### Interface Design
- **Dark Theme**: Optimized for nighttime use with astronomy-friendly color scheme
- **Intuitive Navigation**: Clear workflow from target creation to session planning
- **Real-time Feedback**: Immediate updates as settings and plans are modified
- **Professional Appearance**: Charts and visualizations suitable for serious astrophotography

#### Workflow Optimization
- **Streamlined Target Creation**: Quick setup with intelligent defaults
- **Efficient Session Planning**: Prioritized recommendations with visual planning aids
- **Progress Tracking**: Clear indicators of completion status and remaining work
- **Export Integration**: Seamless transition from planning to observatory execution

### 📊 Statistics
- **8 Major Features** implemented and completed
- **1,400+ lines** of Python application code
- **680+ lines** of HTML template code with advanced JavaScript functionality  
- **270+ lines** of comprehensive roadmap documentation
- **240+ lines** of professional README documentation
- **Extensive testing** on Windows Python 3.14 environment

### 🔧 Dependencies
- Python 3.14+ (tested on 3.14.2)
- Flask 3.0.3 web framework
- SQLAlchemy 2.0.32 database ORM
- Astropy ≥7.2.0 for astronomical calculations
- Astroplan ≥0.10.1 for observation planning
- NumPy ≥2.3.5 for numerical computations
- Chart.js for interactive altitude visualization

### 📝 Documentation
- Comprehensive README with installation and usage instructions
- Detailed feature roadmap with implementation status
- Professional project structure and development guidelines
- Docker support for containerized deployment
- License and contribution guidelines

---

**Release Notes**: This stable release provides a complete astrophotography planning solution suitable for serious amateur astronomers and astrophotographers. All core features are implemented, tested, and ready for production use.

**Next Release Focus**: Future versions will focus on advanced features like AI-driven session recommendation engines, weather integration, and enhanced mobile responsiveness.