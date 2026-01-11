# AstroPlanner – Feature Roadmap  
*Status: Updated to 2026-01-11 | Version 2.1.0-dev (Equipment Presets & AstroBin Integration)*

This document tracks the major features of the AstroPlanner project, what has been completed, and what remains.  
It is intended to be version-controlled in Git for transparency, planning, and future development.

**🎉 Version 1.0.0 Release - Complete Feature Set**  
**🚀 Version 2.0.0-dev - PostgreSQL Support Implementation**  
**🆕 Version 2.1.0-dev - Equipment Presets & AstroBin Integration**

---

## ✅ 1. Treat Each Target as a Project
### Summary  
Originally there was an option to either:
- Treat a target as a top-level object with multiple plans, or  
- Treat every target as its own project.

### Final Decision  
**Each target = one project.**

### Completed
- Added `created_at` to the `Target` model.
- Displayed creation date/time (converted to local timezone).
- Shown on both:
  - Target detail page  
  - Index page  
- Improved visibility using `text-light` + highlighted timestamp.

### Remaining  
Nothing. Feature fully implemented.

---

## ✅ 2. Local Time Zone Handling
### Completed
- Introduced `get_local_tz()` with robust Windows-friendly fallback.
- All timestamps (including created time) now correctly convert:
  - From UTC → Local (UTC+3 by default).
- Eliminated reliance on `tzdata` on systems where it's absent.
- Improved visibility styling.

### Remaining
- Optional: explicitly label sunset/dark/meridian times as “Local Time”.

---

## ✅ 3. Database Rebuild Support
### Completed
- Schema updated with new `created_at` field.
- Provided CLI command `flask --app app.py init-db`.
- Database recreated and validated.

### Remaining  
None.

---

## ✅ 4. NINA Export – Option A (Remaining Subs)
### Completed
- NINA JSON template parsed successfully.
- Dynamic block generation for:
  - Cooling camera  
  - Filter changes  
  - Wait instructions  
  - Exposure sequences  
  - Parking telescope  
- Correct mapping of filter names → wheel positions.
- Export now produces a fully functional NINA Advanced Sequencer JSON.

### Remaining (optional future enhancements)
- Export full plan (not only remaining subs).
- Allow template customization in-app.
- Store multiple export templates.

---

## ✅ 5. Global & Per-Target Configuration (Completed)
### Required
- Global defaults for:
  - Pack-up time
  - Minimum altitude
  - Observer location (lat/lon/elevation)
  - Timezone (fallback to UTC+3)
- Per-target overrides.
- Recompute all dependent information when changed:
  - Window start/end  
  - Midpoint altitude  
  - Chart  
  - NINA export  
  - Status badges  

### Completed
- Added `GlobalConfig` database model with observer location, default settings, and timezone.
- Added `override_packup_time` and `override_min_altitude` fields to `Target` model.
- Created global settings UI at `/settings` with configuration management.
- Created per-target settings UI at `/target/<id>/settings` for overrides.
- Implemented configuration resolution logic with helper functions.
- Updated all window calculations to use configurable parameters instead of hardcoded values.
- Added navigation links in navbar and target detail pages.
- Database initialization automatically creates default global configuration.
- All existing features (window calculations, charts, NINA export) now use configured settings.

### Status  
**✅ Fully implemented and working.**

---

## ✅ 6. Palette Management System (Completed)
### Summary  
Database-driven palette management system allowing custom palettes beyond the hardcoded SHO/HOO/LRGB/LRGBNB options.

### Completed
- **Database Model**: Created `Palette` table with full palette definitions in JSON format
- **Database Schema Updates**: 
  - Added `palette_id` foreign key to `Target` and `TargetPlan` models
  - Maintained backward compatibility with existing `preferred_palette` and `palette_name` string fields
- **Default Palettes**: Automatically initialized system palettes (SHO, HOO, LRGB, LRGBNB) with detailed filter configurations
- **Palette Management UI**:
  - List view showing all available palettes (system and custom)
  - Create new custom palettes with dynamic filter channel configuration
  - Edit existing custom palettes (system palettes are read-only)
  - Delete custom palettes (with safety checks for usage)
  - Navigation integration in main navbar
- **Integration**: Updated target creation and editing forms to use database palettes instead of hardcoded options
- **Filter Configuration**: Each palette stores detailed filter information including:
  - Filter names, labels, and descriptions
  - RGB channel mappings
  - Default exposure times and weights
  - Custom channel configurations

### Technical Implementation
- Palettes stored as JSON in database for maximum flexibility
- Backward compatibility maintained during transition
- System palettes protected from modification/deletion
- Usage validation prevents deletion of palettes in use by targets

### Status  
**✅ Fully implemented and working.**

---

## ✅ 7. Plan & Palette Enhancements
### 7.1 Show Planned & Completed Times in H:M:S
- Planned time currently shown only in minutes.
- Completed exposure totals also shown only in minutes.
- Need:
  - H:M:S formatting ✅
  - Ability to enter total planned time in either:
    - Minutes ✅
    - HH:MM:SS format ✅

### 7.2 Make Frames & Time Inputs Bidirectional
- Changing planned minutes should update # of required subs. ✅
- Changing # of subs should update planned minutes. ✅

### Completed  
- **H:M:S Time Formatting**: Created `time_utils.py` with functions for H:M:S conversion
- **Template Updates**: Updated index.html and target_detail.html to display times in both minutes and H:M:S format
- **Bidirectional Inputs**: 
  - Total planned time can be entered in minutes or H:M:S format with real-time bidirectional conversion
  - Channel-level time inputs also support bidirectional minute ↔ H:M:S conversion
  - Frame count inputs automatically update time fields and vice versa
  - All inputs sync in real-time as users type
- **JavaScript Enhancements**: Added parseHMS(), minutesToHMS(), and enhanced recalcFrames() for full bidirectional functionality

### Status  
**✅ Fully implemented and working.**

---

## ✅ 8. Altitude Chart Enhancements
### Required
- Draw a horizontal line at the altitude threshold (e.g., 30°). ✅
- Shade the region corresponding to the valid imaging window:
  - Inside window: highlighted ✅
  - Outside window: dimmed ✅
- Add current time marker for real-time session planning ✅

### Completed
- **Threshold Line**: Added dashed red line showing minimum altitude threshold with legend
- **Window Shading**: 
  - Green shaded area highlights valid imaging window
  - Gray shading for times outside the imaging window
  - Dashed vertical lines mark window boundaries
- **Enhanced Interactivity**:
  - Improved legend showing both altitude curve and threshold line
  - Enhanced tooltips indicating whether time is within imaging window
  - Grid line coloring to reinforce window visualization
- **Visual Improvements**:
  - Better color scheme with blue altitude curve and red threshold
  - Responsive design with improved hover interactions
  - Custom Chart.js plugin for background shading
- **Real-Time Current Time Marker**: 
  - Orange vertical line showing current time position on chart
  - "Now" label for immediate time reference
  - Smart time interpolation between data points
  - Auto-refresh every minute to stay current
  - Day rollover support for midnight transitions
  - Integration with chart legend
- **Meridian Flip Marker**:
  - Purple dashed vertical line indicating meridian transit time
  - "Meridian" label at top of chart
  - Helps plan imaging sessions around mount flip
  - Interpolated positioning for precise time display
- **Moon Rise/Set Indicators**:
  - Amber dashed vertical lines marking moon rise and set times
  - 🌙↑ and 🌙↓ emoji labels for easy identification
  - Moon presence bar at bottom of chart showing when moon is up
  - Amber-filled sections indicate moon in sky
  - Empty sections indicate moonless (dark sky) imaging time
  - Helps identify optimal imaging windows away from moonlight

### Status  
**✅ Fully implemented and working.**

---

## ✅ 9. Comprehensive Imaging Logs & Session Tracking
### Summary
Complete imaging session tracking and progress logging system to track astrophotography outings and monitor progress across all targets over time.

### Required Features
- **Global Imaging Logs**: Comprehensive view of all imaging sessions across all targets
- **Target-Specific Progress**: Individual target imaging history and progress tracking
- **Session Management**: Enhanced progress tracking with date selection for backdating sessions
- **Statistics & Analytics**: Daily, monthly, and overall imaging statistics
- **Progress Visualization**: Charts and summaries showing imaging activity patterns

### Completed
- **Imaging Logs Page**: 
  - Dedicated `/imaging-logs` route with comprehensive session view
  - Sessions grouped chronologically by imaging date
  - Statistics dashboard showing total imaging days, targets imaged, and session counts
  - Monthly activity summaries with time tracking
  - Navigation integration in main header
- **Enhanced Session Tracking**:
  - Date field added to "Add Imaging Progress" form
  - Support for backdating sessions to record historical data  
  - Improved form layout with date in separate row
  - Fixed database date handling for proper date storage
- **Target-Specific Progress Views**:
  - Individual target imaging history on target detail pages
  - Sessions grouped by date with daily summaries
  - Channel-based progress tracking with time calculations
  - Notes preview with truncation and tooltips
  - Quick link to global imaging logs
- **Statistics & Analytics**:
  - Daily total time calculations per imaging session
  - Monthly activity breakdowns showing days, sessions, and total time
  - Target-specific statistics (total sessions, imaging days, total time)
  - Visual progress indicators and summary cards
- **Data Management**:
  - Enhanced ImagingSession model with proper date handling
  - Efficient database queries for session grouping and statistics
  - Template context improvements for consistent date formatting

### Technical Implementation
- **Database Enhancements**: Fixed date field handling in ImagingSession model
- **Route Management**: New `/imaging-logs` route with grouped session queries
- **Template System**: New `imaging_logs.html` template with responsive design
- **JavaScript Enhancements**: Maintained existing progress calculation functionality
- **UI/UX Improvements**: Bootstrap-based responsive design with color-coded statistics

### User Benefits
- **Session Tracking**: See exactly which days you went out for astrophotography
- **Progress Monitoring**: Track progress on individual targets over time
- **Historical Data**: Backdate sessions to build comprehensive imaging history
- **Analytics**: Understand imaging patterns and productivity trends
- **Planning**: Use historical data to inform future session planning

### Status  
**✅ Fully implemented and working.**

---

## ✅ 10. Enhanced Imaging Progress & Custom Filter System (Completed)
### Summary  
Major enhancements to the imaging progress tracking system, including automated filter selection from target plans and comprehensive custom filter functionality with real-time calculations.

### Completed Features

#### 10.1 Automated Filter Selection
- **Auto-populated Dropdown**: When adding imaging progress, filter dropdown automatically populates with all filters from the current target plan
- **Seamless Integration**: No more manual filter entry - filters are pulled directly from the active target plan
- **Dynamic Updates**: Filter list updates automatically when plan changes are made

#### 10.2 Custom Filter Addition System
- **Interactive Custom Filter Form**: Complete form interface for adding custom filters not in the original plan
- **Real-time Bidirectional Calculations**: 
  - Enter any 2 of: planned minutes, sub exposure time, or frame count
  - Third value automatically calculates in real-time
  - Supports decimal precision for sub-exposure times (e.g., 0.14 seconds for HDR imaging)
- **Comprehensive Input Validation**: Form validation with proper decimal support and range checking
- **Auto-save Functionality**: Adding a custom filter automatically saves the plan without requiring separate "Save Plan" action
- **Weight Configuration**: Custom weight settings for advanced planning scenarios

#### 10.3 Enhanced User Experience
- **Collapsible Interface**: Custom filter form is collapsible to save screen space when not needed
- **Visual Contrast**: Improved button styling with better color contrast for visibility
- **Progress Notes Display**: Fixed note visibility in imaging progress log with proper color contrast
- **Streamlined Workflow**: Single-click custom filter addition with automatic form submission

#### 10.4 Technical Improvements
- **Decimal Precision Support**: Full support for decimal sub-exposure times throughout the system
- **JavaScript Error Resolution**: Fixed variable redeclaration conflicts in calculation functions
- **Backend Decimal Handling**: Updated progress routes to handle float values instead of integer-only
- **Frame Count Preservation**: Custom filter calculations preserve user-specified frame counts
- **Deletion Handling**: Proper marking and removal of custom filters from plans

#### 10.5 Data Integrity & Calculations
- **Bidirectional Input Sync**: Minutes ↔ exposure time ↔ frame count calculations work seamlessly
- **Plan Consistency**: Custom filters integrate with existing plan structure and calculations
- **Real-time Updates**: All plan calculations update immediately when custom filters are added
- **Database Compatibility**: Custom filter data stored consistently with existing plan structure

### 10.6 NINA Export Compatibility & Filter Mapping
- **Custom Filter Mapping**: Custom filters can be mapped to standard NINA filter wheel names for hardware compatibility
- **Intelligent Export System**: NINA export uses mapped filter names instead of custom names for proper telescope integration
- **Filter Dropdown Integration**: Custom filter form includes NINA filter mapping selection with all standard filter names
- **Backward Compatibility**: Existing filters and custom filters without mapping continue to work normally
- **Hardware Integration**: Seamless telescope filter wheel operation with custom filter workflows

### 10.7 Form Validation & Auto-Save Optimization
- **Selective Auto-Save Behavior**: Auto-save only applies to custom filter addition, not plan table modifications
- **Manual Plan Saving**: Plan table changes require explicit "Save Plan" button for user control
- **HTML5 Validation Fixes**: Resolved form validation blocking issues with hidden required fields
- **User Experience**: Improved save behavior prevents unwanted auto-save while maintaining custom filter convenience
- **Form Error Resolution**: Fixed validation conflicts that prevented legitimate form submissions

### 10.8 UI Enhancements & Table Organization
- **Column Reordering**: Improved logical flow by placing "Planned Frames" before "Completed Time" in plan table
- **Collapsible Custom Filter Interface**: Space-efficient design with toggle button and chevron indicator
- **Enhanced Visual Design**: Improved contrast and styling for better visibility and user experience
- **Responsive Layout**: Optimized form layout and spacing for different screen sizes

### 10.9 Imaging Progress Edit & Delete Functionality
- **Edit Session Interface**: Complete edit form for modifying existing imaging sessions with real-time calculations
- **Delete Session with Confirmation**: Safe deletion with confirmation dialog to prevent accidental removals
- **Universal Access**: Edit and delete buttons available in both target detail page and global imaging logs
- **Comprehensive Editing**: Support for modifying date, channel, sub-exposure time, frame count, and session notes
- **Data Integrity**: Form validation ensures data consistency and prevents invalid entries
- **User Experience**: Intuitive pencil (edit) and trash (delete) icons with proper Bootstrap Icons integration
- **Error Handling**: Robust error handling with proper encoding and template management

### Technical Implementation
- **Frontend**: Enhanced JavaScript calculation engine with `recalcFrames()` and `calculateCustomFilterValues()` functions
- **Backend**: Updated Flask routes with proper decimal handling in `add_progress` and `update_plan` endpoints  
- **Database**: Seamless integration with existing JSON plan structure for custom filter persistence
- **NINA Integration**: Enhanced `nina_integration.py` with custom filter mapping support
- **Form Handling**: Improved HTML5 validation management and selective auto-save implementation
- **Edit/Delete Routes**: New `/session/<id>/edit` and `/session/<id>/delete` routes with proper error handling
- **Template System**: UTF-8 encoded `edit_session.html` template with responsive design and real-time updates
- **Bootstrap Assets**: Fresh Bootstrap 5.3.2 and Bootstrap Icons 1.11.3 with proper asset integrity
- **UI/UX**: Bootstrap-based responsive design with collapse functionality and improved accessibility

### User Benefits
- **Simplified Workflow**: No need to manually type filter names - they're auto-populated from plans
- **Flexible Planning**: Can add custom filters on-the-fly for HDR, experimental, or specialized imaging
- **Accurate Calculations**: Real-time bidirectional calculations ensure plan accuracy
- **NINA Hardware Integration**: Custom filters work seamlessly with telescope filter wheels through mapping system
- **Improved Progress Tracking**: Enhanced progress logging with visible notes and better organization
- **Optimized User Control**: Selective auto-save prevents unwanted changes while maintaining convenience
- **Better Data Organization**: Logical column ordering and space-efficient interface design
- **Professional Workflow**: Enterprise-grade form validation and error handling
- **Error Correction**: Easy correction of mistakes in imaging session data without re-entry
- **Data Management**: Complete control over imaging session records with safe deletion options

### Status  
**✅ Fully implemented and working.**

---

## 🟡 11. Session Recommendation Engine with AI-Driven Logic (Pending)
### Summary
Implement an intelligent session recommendation engine that uses AI/ML to optimize imaging sessions based on multiple factors and user preferences.

### Required Features
- **Weather Integration**: Real-time weather data and forecasting
- **Target Priority Scoring**: AI-driven ranking based on:
  - Current target visibility and altitude
  - Weather conditions and forecast
  - Moon phase and illumination impact
  - Historical completion data
  - User preferences and imaging history
- **Session Planning**: Automatically suggest:
  - Best targets for tonight/upcoming nights
  - Optimal imaging order within a session
  - Filter switching recommendations to minimize equipment changes
  - Adaptive scheduling based on changing conditions
- **Machine Learning Components**:
  - Learn from user behavior and preferences
  - Improve recommendations based on session outcomes
  - Adapt to local weather patterns and seeing conditions
- **Integration Features**:
  - Export recommended session plans to NINA
  - Real-time session adjustments based on conditions
  - Historical analysis and recommendation accuracy tracking

### Technical Considerations
- Weather API integration (OpenWeatherMap, Clear Outside, etc.)
- ML framework integration (scikit-learn, TensorFlow Lite, etc.)
- Background scheduling and recommendation updates
- User feedback collection for model training

### Status  
**Feature concept added to roadmap - not yet started.**

---

## 🟡 11.5. PostgreSQL Database Support for Cloud Deployment (Pending)
### Summary
Add PostgreSQL database support to enable deployment on serverless platforms like Google Cloud Run, AWS Lambda, or Kubernetes clusters where SQLite's file-based approach is not suitable.

### Required Features
- **Database Abstraction**: Maintain SQLAlchemy compatibility while supporting both SQLite and PostgreSQL
- **Environment-based Configuration**: Automatic database selection based on environment variables
- **Migration Support**: Database migration scripts that work with both SQLite and PostgreSQL
- **Cloud Deployment Ready**: Configuration for:
  - Google Cloud Run with Cloud SQL PostgreSQL
  - AWS Lambda with RDS PostgreSQL  
  - Kubernetes with PostgreSQL StatefulSet or managed database
  - Docker Compose with PostgreSQL container

### Technical Implementation
- **Connection String Handling**: Enhanced database URL parsing for PostgreSQL connection strings
- **Schema Compatibility**: Ensure all SQLAlchemy models work seamlessly with PostgreSQL
- **Connection Pooling**: Implement proper connection pooling for production PostgreSQL deployments
- **Environment Detection**: Automatic fallback to SQLite for local development, PostgreSQL for production
- **Configuration Management**: Environment variables for:
  - `DATABASE_URL`: Full PostgreSQL connection string
  - `DB_TYPE`: Explicit database type selection (sqlite/postgresql)
  - `DB_POOL_SIZE`: Connection pool configuration
  - `DB_SSL_MODE`: SSL configuration for cloud databases

### Deployment Scenarios
- **Google Cloud Run**: Serverless deployment with Cloud SQL PostgreSQL instance
- **Google Kubernetes Engine (GKE)**: Container deployment with managed PostgreSQL
- **AWS ECS/Fargate**: Serverless containers with RDS PostgreSQL
- **Docker Swarm**: Multi-node deployment with PostgreSQL service
- **Heroku**: Platform-as-a-Service with Heroku PostgreSQL add-on

### Migration Strategy
- **Backward Compatibility**: Existing SQLite installations continue to work unchanged
- **Database Migration Tools**: Scripts to migrate data from SQLite to PostgreSQL
- **Development/Production Parity**: Same codebase works in both environments
- **Testing**: Comprehensive testing on both database backends

### Benefits
- **Scalability**: PostgreSQL supports concurrent users and larger datasets
- **Cloud Native**: Enables deployment on modern serverless and container platforms
- **Production Ready**: Professional database backend suitable for multi-user scenarios
- **High Availability**: PostgreSQL supports replication and failover configurations

### Dependencies
- `psycopg2-binary`: PostgreSQL adapter for Python
- Updated connection string parsing
- Environment-specific configuration files
- Cloud deployment templates (Dockerfile, kubernetes.yaml, etc.)

### Status  
**Feature concept added to roadmap - not yet started.**

---

## 🟡 12. Automatic Recompute Pipeline (Pending)
Any of the following should automatically trigger a full recomputation:
- Changing pack-up time  
- Changing altitude threshold  
- Changing observer location  
- Changing palette  
- Editing planned time or subs  

Affected subsystems:
- Window calculation
- Altitude chart
- Dominant channel
- Total planned exposure
- Remaining subs & time
- NINA export

### Status  
Not started.

---

## 🟡 13. Comprehensive User Guide & Documentation (Pending)
### Summary
Create comprehensive documentation and user guide to help new users get started with AstroPlanner and understand all available features and workflows.

### Required Features
- **Getting Started Guide**: Step-by-step tutorial for first-time users
- **Feature Documentation**: Comprehensive documentation of all features and capabilities
- **Workflow Guides**: Common astrophotography planning workflows and best practices
- **Configuration Documentation**: Detailed setup and configuration instructions
- **Integration Guides**: How to integrate with NINA and other astrophotography software
- **Troubleshooting**: Common issues and solutions
- **FAQ Section**: Frequently asked questions and answers

### Planned Documentation Structure
- **Quick Start Guide**:
  - Installation and initial setup
  - Creating your first target
  - Planning your first imaging session
  - Recording imaging progress
- **Core Features Documentation**:
  - Target management and planning
  - Palette creation and customization  
  - Global and per-target configuration
  - Altitude charts and time windows
  - NINA export functionality
  - Imaging logs and session tracking
- **Advanced Workflows**:
  - Multi-target session planning
  - Filter change optimization
  - Progress tracking strategies
  - Data analysis using imaging logs
- **Technical Documentation**:
  - Observer location setup
  - Timezone configuration
  - Database management
  - Custom palette creation
  - NINA template customization
- **Integration Guides**:
  - NINA Advanced Sequencer integration
  - Export workflows and best practices
  - Equipment setup considerations
- **Troubleshooting & Support**:
  - Common configuration issues
  - Database troubleshooting
  - Performance optimization
  - FAQ and community resources

### Implementation Plan
- **Documentation Website**: Dedicated documentation site or integrated help system
- **Interactive Tutorials**: Step-by-step guided tours within the application
- **Video Guides**: Screen recordings demonstrating key workflows
- **Example Scenarios**: Real-world use cases and example configurations
- **Community Contributions**: Framework for user-contributed guides and tips

### Technical Implementation Options
- **Integrated Help System**: Built-in help pages within the Flask application
- **Static Site Generator**: Separate documentation site (MkDocs, GitBook, etc.)
- **Interactive Tooltips**: Contextual help and tooltips throughout the UI
- **Example Data**: Sample targets and configurations for demonstration
- **Documentation API**: Programmatic access to help content

### User Benefits
- **Reduced Learning Curve**: New users can quickly understand and utilize all features
- **Better Feature Discovery**: Users learn about advanced features they might otherwise miss
- **Improved Workflows**: Guidance on best practices and optimal workflows
- **Self-Service Support**: Users can find answers without external support
- **Community Building**: Shared knowledge base and user contributions

### Success Metrics
- Reduced time-to-first-successful-session for new users
- Increased feature utilization across the user base
- Reduced support requests for basic functionality
- Positive user feedback on documentation quality and completeness

### Status  
**Feature concept added to roadmap - not yet started.**

---

# Summary Table

| Feature | Status | Notes |
|--------|--------|-------|
| Target-as-project design | ✅ Done | Creation timestamp integrated |
| Local timezone support | ✅ Done | Full conversion to UTC+3 |
| Database rebuild support | ✅ Done | CLI command available |
| NINA export (remaining subs) | ✅ Done | Fully functional |
| Global/per-target configuration | ✅ Done | Observer location, pack-up time, min altitude |
| Palette management | ✅ Done | Database-driven with custom palette support |
| Plan & Palette Enhancements | ✅ Done | H:M:S formatting and bidirectional frame/time inputs |
| Altitude chart enhancements | ✅ Done | Threshold lines, window shading, current time marker |
| Imaging logs & session tracking | ✅ Done | Comprehensive progress tracking with analytics |
| Enhanced imaging progress & custom filters | ✅ Done | Auto-populated filters, custom filter addition, collapsible UI |
| Session recommendation engine | 🟡 Pending | AI-driven session optimization |
| PostgreSQL database support | ✅ Done | Cloud deployment readiness |
| Equipment presets & AstroBin integration | ✅ Done | Multi-user filter setup, CSV export |
| Automatic recomputation | 🟡 Pending | After changes to settings |
| Comprehensive user guide & documentation | 🟡 Pending | Getting started guides, tutorials, and feature documentation |
| Filter & channel management | 🟡 In Progress | Multi-wheel support, NINA integration |

---

## ✅ 11.5. PostgreSQL Database Support
### Summary  
Enable cloud deployment and production-ready database infrastructure by implementing dual database support with runtime selection between SQLite (development) and PostgreSQL (production).

### Completed
- **Core Database Abstraction**: 
  - `config/database.py`: Environment-based database configuration with auto-detection
  - Support for SQLite and PostgreSQL with proper connection pooling
  - Cloud platform detection (Heroku, Railway, Render) with automatic configuration
  
- **Migration Engine**: 
  - `config/migration.py`: Bidirectional data migration between database types
  - Data validation, backup creation, and integrity checking
  - Rollback capabilities and comprehensive error handling
  
- **CLI Management Tools**:
  - `flask db info`: Display current database configuration and test connection
  - `flask db init`: Initialize database schema with default data
  - `flask db migrate`: Migrate data between SQLite and PostgreSQL
  - `flask db backup`: Create database backups
  - `flask db reset`: Reset database for development
  
- **Production Deployment**:
  - Environment configuration templates (`.env.example`, `.env.production`)
  - Complete deployment guide (`POSTGRESQL_DEPLOYMENT.md`)
  - Support for Heroku, Railway, Render, Docker, and Kubernetes
  - SSL configuration and security hardening
  
- **Testing Framework**:
  - Comprehensive test suite for both database types
  - Test runner with database-specific configurations
  - Parametrized tests ensuring feature parity

### Technical Benefits
- **Development**: Continue using SQLite for local development
- **Production**: Deploy with PostgreSQL for better performance and reliability
- **Cloud Ready**: Seamless deployment on any cloud platform
- **Data Safety**: Proven migration and backup systems
- **Scalability**: Connection pooling and performance optimization

### Remaining  
Nothing. Feature fully implemented and production-ready.

---

---

## 🟡 14. Filter & Channel Management System (Pending)
### Summary
Three-tier filter management system: app-wide filter types, multiple filter wheel hardware profiles, and per-wheel slot mappings. Replaces hardcoded filter definitions with database-driven configuration. Full NINA compatibility with flexible naming.

### Architecture
- **Filter**: Abstract filter type (Ha, OIII, SII, L, R, G, B, LP) with display name, type (narrowband/broadband), default exposure
- **FilterWheel**: Physical hardware profile (name, slot count, filter size, NINA profile name)
- **FilterWheelSlot**: Position mapping linking filters to wheel slots with NINA-specific names and optional brand info

### Planned Features
- Filter CRUD with system filter protection (soft-delete/deactivate only)
- Filter wheel CRUD with slot assignment interface
- Wheel activation validation (warn if active plans use unmapped filters)
- PaletteFilter association (future: replace filters_json in palettes)
- NINA integration update to use active wheel configuration
- Migration from existing filters_json with backup
- API endpoints for dynamic dropdowns (`/api/filters`, `/api/active-wheel`)

### Database Models Added
```
filters                    filter_wheels              filter_wheel_slots
- id                       - id                       - id
- name (code)              - name                     - filter_wheel_id (FK)
- display_name             - slot_count               - filter_id (FK)
- filter_type              - filter_size              - position
- default_exposure         - nina_profile_name        - nina_filter_name
- is_system                - is_active                - physical_filter_brand
- is_active                - is_default               - notes

palette_filters
- id
- palette_id (FK)
- filter_id (FK)
- rgb_channel
- weight
- order
```

### 14.1 Future Enhancements (Planned)
- **Visual Wheel Diagram**: Drag-drop slot assignment interface for intuitive configuration
- **Per-Target Wheel Override**: Allow targets to specify which wheel to use for mixed imaging setups
- **Profile Export/Import**: Backup and restore filter wheel configurations

### Status
**🟡 In Progress - Core implementation complete, testing and refinement ongoing.**

---

## ✅ 15. Equipment Presets & AstroBin Integration (Completed)
### Summary
Multi-user equipment configuration system with JSON-based presets and AstroBin CSV export functionality. Enables easy sharing of filter configurations across installations and seamless acquisition data upload to AstroBin.

### Completed Features

#### 15.1 Equipment Preset System
- **JSON-Based Presets**: Modular configuration files in `config/presets/`
  - `base.json`: Core palettes, target types, and default filter wheel configuration
  - `filters/generic.json`: Standard filter set without AstroBin IDs (default)
  - `filters/zwo.json`: ZWO 1.25" filters with AstroBin equipment database IDs
- **Flexible Database Initialization**: 
  - `--mode starter|minimal`: Full setup vs. filters-only initialization
  - `--filter-preset <name>`: Select which filter preset to use
  - `--force`: Force re-initialization with data clearing
- **CLI Preset Management**:
  - `flask list-presets`: Display available filter presets with details
  - `flask export-preset <file.json>`: Export current configuration
  - `flask import-preset <file.json>`: Import with merge or replace options
- **Web UI Integration**: Settings page with import/export functionality
  - Export current filters and filter wheels as JSON download
  - Import from JSON files with merge or replace modes
  - Download built-in presets directly from the UI

#### 15.2 AstroBin Integration
- **Filter AstroBin IDs**: Database field to store AstroBin equipment database IDs
  - Each filter can store its numeric AstroBin ID (e.g., Ha=1955, OIII=2707)
  - IDs are preserved in preset export/import operations
- **Per-Target CSV Export**: AstroBin-compatible acquisition CSV export
  - Date, filter ID, number of subs, duration, binning, gain, sensor cooling
  - Proper filter name mapping from channel names to base filters
  - Warning system for filters missing AstroBin IDs
- **Flexible Export Settings**: Modal dialog with configurable options
  - Binning (1x1, 2x2, etc.)
  - Gain setting
  - Sensor cooling temperature
  - Default calibration frames (all "0" per AstroBin format)
  - Default Bortle scale value

#### 15.3 Database Enhancements
- **Filter Model Updates**: Added `astrobin_id` column to Filter model
- **Migration Support**: `flask migrate-db` handles schema updates
- **Filter Form Enhancement**: AstroBin ID input in filter create/edit form

### Technical Implementation
- **Preset Files**: JSON-based configuration in `config/presets/` directory
- **CLI Commands**: Click-based commands with comprehensive options
- **Web Routes**: `/settings/export-preset`, `/settings/import-preset`, `/settings/download-preset/<name>`
- **AstroBin Export**: `/target/<id>/export-astrobin-csv` route with modal form
- **Filter Mapping**: Smart mapping from NINA channel names to base filter AstroBin IDs

### User Benefits
- **Easy Multi-User Setup**: New users can initialize with brand-specific presets
- **Equipment Sharing**: Export and share filter configurations between users
- **AstroBin Compatibility**: Direct CSV upload to AstroBin acquisition logs
- **Flexible Initialization**: Choose between full setup or minimal filters-only mode
- **Preserve Custom Configs**: Export before updates, import to restore

### CLI Usage Examples
```bash
# List available presets
flask list-presets

# Initialize with ZWO filters (includes AstroBin IDs)
flask init-db --filter-preset zwo

# Initialize minimal setup (filters only, no palettes/wheels)
flask init-db --mode minimal --filter-preset generic

# Force reinitialize with different preset
flask init-db --filter-preset zwo --force

# Export current configuration
flask export-preset my_equipment.json --include-wheels

# Import configuration (merge with existing)
flask import-preset shared_filters.json --merge

# Import configuration (replace all)
flask import-preset new_setup.json --include-wheels
```

### Status
**✅ Fully implemented and working.**

---

# Next Recommended Focus
**11. Session Recommendation Engine** - AI-driven session optimization  
Now that the core planning features are complete (time formatting, palette management, altitude visualization, imaging logs, and enhanced custom filter system), the next major enhancement is implementing an intelligent session recommendation engine. This ambitious feature includes:
- Weather integration and forecasting
- AI-driven target priority scoring based on multiple factors
- Automatic session planning and filter switching recommendations
- Machine learning to adapt to user behavior and local conditions

Alternative focus areas:
- **14. Filter & Channel Management System** - Hardware configuration for multi-wheel setups (in progress)
- **13. Comprehensive User Guide & Documentation** - Getting started guides, tutorials, and feature documentation to improve user onboarding
- **12. Automatic Recomputation** - Dynamic updates when settings change
- **Additional Export Formats** - More observatory software integrations
- **Mobile Responsiveness** - Enhanced mobile interface optimizations

---

# End of Roadmap
