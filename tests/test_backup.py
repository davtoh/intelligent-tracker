#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for State Persistence, Auto-Restore & Full Backup Migration (Milestone 7).
"""

from __future__ import division, print_function, absolute_import

import os
import sys
import json
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
import subprocess

from intelligent_tracker.backup import BackupManager, calculate_sha256
from intelligent_tracker.database import TrackerDB


class TestBackupMigration(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="tracker_backup_test_")
        self.db_path = os.path.join(self.test_dir, "data", "tracker.db")
        self.crops_dir = os.path.join(self.test_dir, "data", "crops")
        self.configs_dir = os.path.join(self.test_dir, "configs")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.crops_dir, exist_ok=True)
        os.makedirs(self.configs_dir, exist_ok=True)

        # Seed test database with entities and sightings
        self.db = TrackerDB(self.db_path)
        ent_id = self.db.add_entity(name="Test Subject 01", category="vip", notes="VIP executive")
        self.db.add_signature(entity_id=ent_id, embedding=[0.1] * 512, crop_path=os.path.join(self.crops_dir, "crop_01.jpg"))
        self.db.record_sighting(entity_id=ent_id, track_id=1, source="cam_01", zone_id="lobby", confidence=0.98)

        # Create sample crop file
        with open(os.path.join(self.crops_dir, "crop_01.jpg"), "wb") as f:
            f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb")

        # Create sample config file
        with open(os.path.join(self.configs_dir, "cameras.json"), "w", encoding="utf-8") as f:
            json.dump([{"id": "cam_01", "name": "Entrance", "source": "synthetic"}], f)

        self.manager = BackupManager(
            db_path=self.db_path,
            crops_dir=self.crops_dir,
            configs_dir=self.configs_dir,
        )

    def tearDown(self):
        if hasattr(self, "db") and self.db:
            self.db.close()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_calculate_sha256(self):
        """Verify sha256 checksum generation on sample file."""
        test_file = os.path.join(self.test_dir, "sample.txt")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("intelligent-tracker-backup")
        h = calculate_sha256(test_file)
        self.assertIsInstance(h, str)
        self.assertEqual(len(h), 64)

    def test_02_create_backup_zip_and_manifest(self):
        """Verify backup creation packages DB, crops, configs and manifest.json."""
        out_zip = os.path.join(self.test_dir, "test_backup.zip")
        generated_path = self.manager.create_backup(output_path=out_zip, include_crops=True)
        self.assertTrue(os.path.exists(generated_path))

        with zipfile.ZipFile(generated_path, "r") as z:
            names = z.namelist()
            self.assertIn("manifest.json", names)
            self.assertIn("data/tracker.db", names)
            self.assertTrue(any("crop_01.jpg" in n for n in names))
            self.assertTrue(any("cameras.json" in n for n in names))

            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
            self.assertEqual(manifest["version"], "1.0.0")
            self.assertIn("database_stats", manifest)
            self.assertEqual(manifest["database_stats"]["entities"], 1)
            self.assertEqual(manifest["database_stats"]["sightings"], 1)

    def test_03_inspect_backup_archive(self):
        """Verify inspect_backup reads manifest without extracting files."""
        out_zip = os.path.join(self.test_dir, "inspect_test.zip")
        self.manager.create_backup(output_path=out_zip)

        info = self.manager.inspect_backup(out_zip)
        self.assertIn("version", info)
        self.assertIn("database_stats", info)
        self.assertEqual(info["database_stats"]["entities"], 1)
        self.assertGreater(len(info["files"]), 0)

    def test_04_restore_backup_archive(self):
        """Verify full system restoration into a fresh target environment."""
        out_zip = os.path.join(self.test_dir, "export.zip")
        self.manager.create_backup(output_path=out_zip)

        # Create separate clean target environment
        restore_dir = tempfile.mkdtemp(prefix="tracker_restore_")
        target_db = os.path.join(restore_dir, "data", "tracker.db")
        target_crops = os.path.join(restore_dir, "data", "crops")
        target_configs = os.path.join(restore_dir, "configs")

        restore_manager = BackupManager(
            db_path=target_db,
            crops_dir=target_crops,
            configs_dir=target_configs,
        )

        try:
            report = restore_manager.restore_backup(out_zip)
            self.assertTrue(report["success"])
            self.assertGreater(report["restored_files_count"], 0)
            self.assertEqual(report["database_stats"]["entities"], 1)

            # Verify target files exist and can be queried
            self.assertTrue(os.path.exists(target_db))
            restored_db = TrackerDB(target_db)
            ents = restored_db.list_entities()
            self.assertEqual(len(ents), 1)
            self.assertEqual(ents[0]["name"], "Test Subject 01")
            restored_db.close()

            # Verify crop restored
            self.assertTrue(os.path.exists(os.path.join(target_crops, "crop_01.jpg")))
        finally:
            shutil.rmtree(restore_dir, ignore_errors=True)

    def test_05_zip_slip_security_guard(self):
        """Verify restore ignores potentially malicious path traversal entries (Zip Slip)."""
        malicious_zip = os.path.join(self.test_dir, "malicious.zip")
        with zipfile.ZipFile(malicious_zip, "w") as z:
            z.writestr("manifest.json", json.dumps({"version": "1.0.0"}))
            # Attempt to write outside target sandbox
            z.writestr("../../../evil.txt", "exploit")

        restore_dir = tempfile.mkdtemp(prefix="tracker_slip_test_")
        sec_manager = BackupManager(
            db_path=os.path.join(restore_dir, "db.sqlite"),
            crops_dir=os.path.join(restore_dir, "crops"),
            configs_dir=os.path.join(restore_dir, "cfg"),
        )
        try:
            sec_manager.restore_backup(malicious_zip)
            # Evil file should NOT have been created outside sandbox
            parent_evil = os.path.abspath(os.path.join(restore_dir, "..", "..", "..", "evil.txt"))
            self.assertFalse(os.path.exists(parent_evil))
        finally:
            shutil.rmtree(restore_dir, ignore_errors=True)

    def test_06_cli_export_and_info(self):
        """Verify CLI interface with --export and --info flags."""
        cli_zip = os.path.join(self.test_dir, "cli_backup.zip")
        cmd_export = [
            sys.executable, "-m", "intelligent_tracker.backup",
            "--export", cli_zip,
            "--db", self.db_path,
            "--crops", self.crops_dir,
            "--configs", self.configs_dir,
        ]
        ret = subprocess.run(cmd_export, capture_output=True, text=True)
        self.assertEqual(ret.returncode, 0)
        self.assertTrue(os.path.exists(cli_zip))

        cmd_info = [
            sys.executable, "-m", "intelligent_tracker.backup",
            "--info", cli_zip,
        ]
        ret_info = subprocess.run(cmd_info, capture_output=True, text=True)
        self.assertEqual(ret_info.returncode, 0)
        self.assertIn("INTELLIGENT TRACKER BACKUP MANIFEST", ret_info.stdout)
        self.assertIn("DB Entities:  1", ret_info.stdout)


if __name__ == "__main__":
    unittest.main()
