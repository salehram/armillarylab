"""Tests for ObjectMapping-driven target_type override."""
from __future__ import annotations

import pytest

from resolver.types import ResolvedObject
from resolver.overrides import apply_override


@pytest.fixture
def app_ctx():
    from app import app, db, TargetType, ObjectMapping
    app.config["TESTING"] = True
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        # Seed the 8 canonical target_types
        for name in ("emission", "galaxy", "cluster", "planetary",
                     "supernova_remnant", "reflection", "diffuse", "other"):
            db.session.add(TargetType(name=name, recommended_palette="SHO",
                                      description=name))
        db.session.commit()
        yield {
            "db": db, "TargetType": TargetType, "ObjectMapping": ObjectMapping,
        }
        db.session.remove()
        db.drop_all()


def _link(app_ctx, object_name: str, type_name: str):
    db = app_ctx["db"]
    tt = app_ctx["TargetType"].query.filter_by(name=type_name).first()
    db.session.add(app_ctx["ObjectMapping"](object_name=object_name,
                                            target_type_id=tt.id))
    db.session.commit()


class TestOverride:
    def test_no_mapping_keeps_target_type(self, app_ctx):
        obj = ResolvedObject(canonical_name="M 31", ra_hours=0.7, dec_deg=41.2,
                             target_type="galaxy", source="simbad")
        apply_override(obj)
        assert obj.target_type == "galaxy"
        assert "override" not in obj.source

    def test_override_by_canonical_name(self, app_ctx):
        _link(app_ctx, "NGC 7000", "emission")
        obj = ResolvedObject(canonical_name="NGC 7000", ra_hours=20.97,
                             dec_deg=44.3, target_type="other", source="simbad")
        apply_override(obj)
        assert obj.target_type == "emission"
        assert "override" in obj.source

    def test_override_by_input_name(self, app_ctx):
        _link(app_ctx, "M 1", "supernova_remnant")
        obj = ResolvedObject(canonical_name="NGC 1952", ra_hours=5.5, dec_deg=22.0,
                             target_type="other", input_name="M 1", source="simbad")
        apply_override(obj)
        assert obj.target_type == "supernova_remnant"

    def test_override_by_common_name(self, app_ctx):
        _link(app_ctx, "Eastern Veil Nebula", "supernova_remnant")
        obj = ResolvedObject(
            canonical_name="NGC 6992", ra_hours=20.95, dec_deg=31.7,
            target_type="emission",  # wrong upstream value
            common_names=["Eastern Veil Nebula"], source="simbad",
        )
        apply_override(obj)
        assert obj.target_type == "supernova_remnant"

    def test_override_is_case_insensitive(self, app_ctx):
        _link(app_ctx, "ngc 7000", "emission")
        obj = ResolvedObject(canonical_name="NGC 7000", ra_hours=20.97,
                             dec_deg=44.3, target_type="other", source="x")
        apply_override(obj)
        assert obj.target_type == "emission"

    def test_returns_same_instance(self, app_ctx):
        obj = ResolvedObject(canonical_name="X", ra_hours=0, dec_deg=0,
                             target_type="other", source="x")
        result = apply_override(obj)
        assert result is obj


class TestNoAppContext:
    def test_silent_noop(self):
        obj = ResolvedObject(canonical_name="M 31", ra_hours=0.7, dec_deg=41.2,
                             target_type="galaxy", source="simbad")
        apply_override(obj)
        assert obj.target_type == "galaxy"
