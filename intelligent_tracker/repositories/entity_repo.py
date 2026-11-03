"""
Entity Repository Mixin.

Manages entity registration, updates, retrieval, deletion, and high-level
enrollment workflows for tracked objects, persons, and vehicles.
"""

import os
import time
from typing import Optional, Dict, Any, Tuple, List
import numpy as np
import cv2


class EntityMixin:
    """Provides entity CRUD operations and high-level enrollment logic."""

    def add_entity(
        self,
        name: str,
        category: str = "person",
        status: str = "active",
        notes: str = "",
    ) -> int:
        """
        Register a new entity in the database.

        :return: Created entity ID.
        """
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO entities (name, category, status, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (name.strip(), category.strip(), status.strip(), notes.strip(), now, now),
                )
                self._conn.commit()
                return cursor.lastrowid
            finally:
                cursor.close()

    def update_entity(
        self,
        entity_id: int,
        name: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Update fields of an existing entity.

        :return: True if entity was found and updated.
        """
        fields = []
        values = []

        if name is not None:
            fields.append("name = ?")
            values.append(name.strip())
        if category is not None:
            fields.append("category = ?")
            values.append(category.strip())
        if status is not None:
            fields.append("status = ?")
            values.append(status.strip())
        if notes is not None:
            fields.append("notes = ?")
            values.append(notes.strip())

        if not fields:
            return False

        fields.append("updated_at = ?")
        values.append(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
        values.append(entity_id)

        query = "UPDATE entities SET {} WHERE id = ?".format(", ".join(fields))

        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(query, values)
                self._conn.commit()
                return cursor.rowcount > 0
            finally:
                cursor.close()

    def get_entity(self, entity_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve single entity by ID."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
            finally:
                cursor.close()

    def get_entity_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Retrieve single entity by name."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("SELECT * FROM entities WHERE name = ?", (name.strip(),))
                row = cursor.fetchone()
                return dict(row) if row else None
            finally:
                cursor.close()

    def list_entities(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List registered entities with optional category and status filtering.

        :return: List of entity dictionaries.
        """
        query = "SELECT * FROM entities"
        conditions = []
        params = []

        if category is not None:
            conditions.append("category = ?")
            params.append(category.strip())
        if status is not None:
            conditions.append("status = ?")
            params.append(status.strip())

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id ASC"

        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
            finally:
                cursor.close()

    def delete_entity(self, entity_id: int) -> bool:
        """
        Delete an entity and cascade-delete all its signatures.

        :return: True if an entity was deleted.
        """
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
                self._conn.commit()
                return cursor.rowcount > 0
            finally:
                cursor.close()

    def enroll_entity(
        self,
        name: str,
        category: str = "person",
        frame: Optional[np.ndarray] = None,
        bbox: Optional[Tuple[int, int, int, int]] = None,
        embedding: Optional[np.ndarray] = None,
        notes: str = "",
        extractor: Optional[Any] = None,
        save_crop_dir: Optional[str] = "data/crops",
        is_anchor: bool = True,
    ) -> Dict[str, Any]:
        """
        Convenience method to register an entity, extract its visual crop,
        compute embedding vector, save thumbnail crop, and store signature.

        :param name: Entity name (e.g. 'Forklift #02', 'Alice').
        :param category: Category (e.g. 'staff', 'vip', 'vehicle').
        :param frame: Full BGR frame containing the entity.
        :param bbox: (x, y, w, h) bounding box.
        :param embedding: Precomputed embedding (optional if extractor provided).
        :param notes: Metadata notes.
        :param extractor: BaseFeatureExtractor instance (optional if embedding provided).
        :param save_crop_dir: Directory where thumbnail crop image should be saved.
        :param is_anchor: If True, marks signature as a ground-truth Locked Anchor.
        :return: Created entity info dict with signature_id and crop_path.
        """
        crop_path = ""
        computed_embedding = embedding

        if frame is not None and bbox is not None:
            x, y, w, h = [int(v) for v in bbox]
            ih, iw = frame.shape[:2]
            x1 = max(0, min(x, iw - 1))
            y1 = max(0, min(y, ih - 1))
            x2 = max(x1 + 1, min(x + w, iw))
            y2 = max(y1 + 1, min(y + h, ih))
            crop = frame[y1:y2, x1:x2]

            # Compute embedding via extractor if not supplied
            if computed_embedding is None and extractor is not None:
                computed_embedding = extractor.extract_crop(crop)

            # Save crop thumbnail
            if save_crop_dir and crop.size > 0:
                os.makedirs(save_crop_dir, exist_ok=True)
                crop_filename = "{}_{}_{}.jpg".format(
                    name.replace(" ", "_").lower(),
                    int(time.time()),
                    np.random.randint(1000, 9999),
                )
                crop_path = os.path.join(save_crop_dir, crop_filename)
                cv2.imwrite(crop_path, crop)

        # Check if entity already exists by name
        existing = self.get_entity_by_name(name)
        if existing:
            entity_id = existing["id"]
            self.update_entity(entity_id, category=category, notes=notes)
        else:
            entity_id = self.add_entity(name=name, category=category, notes=notes)

        # Add signature if embedding is available
        signature_id = None
        if computed_embedding is not None:
            signature_id = self.add_signature(
                entity_id=entity_id,
                embedding=computed_embedding,
                crop_path=crop_path,
                is_anchor=1 if is_anchor else 0,
                locked=1 if is_anchor else 0,
            )

        entity_data = self.get_entity(entity_id) or {}
        entity_data["signature_id"] = signature_id
        entity_data["crop_path"] = crop_path
        return entity_data

