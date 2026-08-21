"""Rekordbox XML writer for exporting cues in collection XML format (Automark-for-Rekordbox style)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from rekordbox_mcp.domain.models import CuePoint, Track


class RekordboxXmlWriter:
    """
    Writes Rekordbox collection XML with cue points (POSITION_MARK).
    
    XML Schema:
    - Root: DJ_PLAYLISTS > COLLECTION > TRACK
    - TRACK attributes: TrackID, Name, Artist, AverageBpm, TotalTime, Location
    - POSITION_MARK attributes: Name, Type, Start, End, Num
      - Type: "0"=cue, "4"=loop
      - Num: hot cue 0-7, memory cue -1
      - Start/End: seconds (ms / 1000)
    """

    def __init__(self, xml_path: str | Path | None = None):
        self._xml_path = Path(xml_path) if xml_path else None
        self._tree: ET.ElementTree | None = None
        self._root: ET.Element | None = None
        self._collection: ET.Element | None = None
        self._tracks_cache: dict[int, ET.Element] = {}

    def load_xml(self, path: str | Path) -> None:
        """Load existing Rekordbox collection XML."""
        self._xml_path = Path(path)
        self._tree = ET.parse(self._xml_path)
        self._root = self._tree.getroot()
        
        # Find COLLECTION element
        self._collection = self._root.find(".//COLLECTION")
        if self._collection is None:
            # Create structure if not exists
            self._create_default_structure()
        
        # Cache track elements for fast lookup
        self._tracks_cache = {}
        for track_elem in self._collection.findall("TRACK"):
            track_id = track_elem.get("TrackID")
            if track_id:
                self._tracks_cache[int(track_id)] = track_elem

    def _create_default_structure(self) -> None:
        """Create default DJ_PLAYLISTS structure."""
        self._root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
        playlists = ET.SubElement(self._root, "PLAYLISTS")
        ET.SubElement(playlists, "NODE", Type="0", Name="ROOT", Count="0", Entry="0")
        self._collection = ET.SubElement(self._root, "COLLECTION", Entries="0")
        self._tree = ET.ElementTree(self._root)

    def get_or_create_track_element(self, track: Track) -> ET.Element:
        """Get existing TRACK element or create new one."""
        if track.id in self._tracks_cache:
            return self._tracks_cache[track.id]

        if self._collection is None:
            self._create_default_structure()

        # Create TRACK element with required attributes
        track_elem = ET.SubElement(self._collection, "TRACK")
        track_elem.set("TrackID", str(track.id))
        track_elem.set("Name", track.title)
        track_elem.set("Artist", track.artist)
        track_elem.set("AverageBpm", str(int(track.bpm * 100)))  # BPM * 100
        track_elem.set("TotalTime", str(int(track.duration_ms / 1000)))  # seconds
        
        # Location attribute (file:// URL)
        if track.analysis_path:
            # Convert analysis path to audio file location
            location = track.analysis_path.replace(".anlz", "").replace("/Analysis/", "/")
            if not location.startswith("file://"):
                location = "file://" + location
            track_elem.set("Location", location)
        else:
            track_elem.set("Location", "file:///unknown")

        # Other optional attributes
        if track.key:
            track_elem.set("Tonality", track.key)
        if track.genre:
            track_elem.set("Genre", track.genre)

        self._tracks_cache[track.id] = track_elem
        return track_elem

    def add_cue_to_track(self, track_element: ET.Element, cue: CuePoint) -> ET.Element:
        """
        Add a POSITION_MARK to a TRACK element.
        
        Args:
            track_element: TRACK XML element
            cue: CuePoint to add
            
        Returns:
            The created POSITION_MARK element
        """
        # Remove existing POSITION_MARK with same Num if hot cue
        if cue.is_hot_cue and cue.hot_cue_num is not None:
            self._remove_hot_cue_by_num(track_element, cue.hot_cue_num)

        position_mark = ET.SubElement(track_element, "POSITION_MARK")
        position_mark.set("CueID", cue.id)
        
        # Name (comment or default)
        name = cue.comment if cue.comment else self._get_default_cue_name(cue)
        position_mark.set("Name", name)
        
        # Type: "0"=cue, "4"=loop
        if cue.is_loop:
            position_mark.set("Type", "4")
        else:
            position_mark.set("Type", "0")
        
        # Start time in seconds
        start_sec = cue.position_ms / 1000.0
        position_mark.set("Start", f"{start_sec:.3f}")
        
        # End time in seconds (for loops)
        if cue.is_loop and cue.loop_end_ms:
            end_sec = cue.loop_end_ms / 1000.0
            position_mark.set("End", f"{end_sec:.3f}")
        else:
            position_mark.set("End", f"{start_sec:.3f}")
        
        # Num: hot cue 0-7, memory cue -1
        if cue.is_hot_cue and cue.hot_cue_num is not None:
            # hot_cue_num is 1-8, convert to 0-7
            position_mark.set("Num", str(cue.hot_cue_num - 1))
        elif cue.is_memory_cue:
            position_mark.set("Num", "-1")
        else:
            position_mark.set("Num", "-1")
        
        # Color attributes for hot cues
        if cue.is_hot_cue:
            if cue.color_table_index is not None:
                position_mark.set("ColorTableIndex", str(cue.color_table_index))
            if cue.color >= 0:
                position_mark.set("Color", str(cue.color))
        
        return position_mark

    def get_cues_for_track(self, track_id: int) -> list[CuePoint]:
        """Read cue points from the currently loaded XML collection."""
        if self._xml_path and self._xml_path.exists() and self._tree is None:
            self.load_xml(self._xml_path)
        track_elem = self._tracks_cache.get(track_id)
        if track_elem is None:
            return []
        number_to_kind = {0: 1, 1: 2, 2: 3, 3: 5, 4: 6, 5: 7, 6: 8, 7: 9}
        cues = []
        for index, mark in enumerate(track_elem.findall("POSITION_MARK")):
            num = int(mark.get("Num", "-1"))
            kind = 0 if num == -1 else number_to_kind.get(num, 1)
            start = float(mark.get("Start", "0")) * 1000
            end = float(mark.get("End", "0")) * 1000
            cues.append(CuePoint(
                id=mark.get("CueID", f"xml_{track_id}_{index}"),
                track_id=track_id,
                kind=kind,
                position_ms=start,
                loop_end_ms=end if mark.get("Type") == "4" and end > start else None,
                color_table_index=int(mark.get("ColorTableIndex")) if mark.get("ColorTableIndex") else None,
                color=int(mark.get("Color", "0")),
                comment=mark.get("Name", ""),
            ))
        return cues

    def _remove_hot_cue_by_num(self, track_element: ET.Element, hot_cue_num: int) -> None:
        """Remove existing hot cue with the same number (0-7)."""
        num_attr = str(hot_cue_num - 1)  # Convert 1-8 to 0-7
        for pos_mark in track_element.findall("POSITION_MARK"):
            if pos_mark.get("Num") == num_attr and pos_mark.get("Type") == "0":
                track_element.remove(pos_mark)

    def _get_default_cue_name(self, cue: CuePoint) -> str:
        """Get default name for cue based on kind."""
        kind_names = {
            1: "First Beat",
            2: "Loop In",
            3: "Vocal / Buildup",
            5: "Drop",
            6: "Breakdown",
            7: "Special",
            8: "Outro",
            9: "Loop Out",
        }
        if cue.is_memory_cue:
            return "Memory Cue"
        return kind_names.get(cue.kind, f"Cue {cue.kind}")

    def remove_cues_from_track(self, track_element: ET.Element, cue_types: list[str] | None = None) -> int:
        """
        Remove POSITION_MARK elements from a TRACK.
        
        Args:
            track_element: TRACK XML element
            cue_types: List of types to remove ("hot", "memory", "loop", or None for all)
            
        Returns:
            Number of cues removed
        """
        removed = 0
        to_remove = []
        
        for pos_mark in track_element.findall("POSITION_MARK"):
            should_remove = False
            
            if cue_types is None:
                should_remove = True
            else:
                num = pos_mark.get("Num")
                type_attr = pos_mark.get("Type")
                
                if "hot" in cue_types and num != "-1" and type_attr == "0":
                    should_remove = True
                elif "memory" in cue_types and num == "-1" and type_attr == "0":
                    should_remove = True
                elif "loop" in cue_types and type_attr == "4":
                    should_remove = True
            
            if should_remove:
                to_remove.append(pos_mark)
        
        for elem in to_remove:
            track_element.remove(elem)
            removed += 1
        
        return removed

    def write_cues_to_xml(self, track_id: int, cues: list[CuePoint], output_path: str | Path) -> None:
        """
        Write cues for a track to XML file.
        
        Args:
            track_id: Track ID
            cues: List of CuePoint objects
            output_path: Output XML file path
        """
        # Load or create XML
        if self._xml_path and self._xml_path.exists():
            self.load_xml(self._xml_path)
        else:
            self._create_default_structure()
        
        # Get or create track element (need a minimal Track object)
        track = Track(
            id=track_id,
            title="Unknown",
            artist="Unknown",
            bpm=128.0,
            duration_ms=300000,
            analysis_path="",
        )
        track_elem = self.get_or_create_track_element(track)
        
        # Remove existing cues first
        self.remove_cues_from_track(track_elem)
        
        # Add new cues
        for cue in cues:
            cue.track_id = track_id
            self.add_cue_to_track(track_elem, cue)
        
        # Save
        self.save(output_path)

    def save(self, path: str | Path | None = None) -> None:
        """Save XML to file with pretty printing."""
        save_path = Path(path) if path else self._xml_path
        if not save_path:
            raise ValueError("No output path specified")
        
        if self._tree is None:
            raise RuntimeError("No XML loaded or created")
        
        # Pretty print
        self._indent(self._root)
        
        # Write with XML declaration
        self._tree.write(save_path, encoding="utf-8", xml_declaration=True)

    def _indent(self, elem: ET.Element, level: int = 0) -> None:
        """Add indentation for pretty printing."""
        indent = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = indent + "  "
            if not elem.tail or not elem.tail.strip():
                elem.tail = indent
            for child in elem:
                self._indent(child, level + 1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = indent
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = indent

    def get_track_element(self, track_id: int) -> ET.Element | None:
        """Get TRACK element by ID."""
        return self._tracks_cache.get(track_id)

    def update_collection_entries(self) -> None:
        """Update the Entries attribute on COLLECTION element."""
        if self._collection is not None:
            self._collection.set("Entries", str(len(self._tracks_cache)))

    def create_track_element(self, track: Track) -> ET.Element:
        """Create a new TRACK element with all attributes."""
        if self._collection is None:
            self._create_default_structure()
        
        track_elem = ET.SubElement(self._collection, "TRACK")
        track_elem.set("TrackID", str(track.id))
        track_elem.set("Name", track.title)
        track_elem.set("Artist", track.artist)
        track_elem.set("AverageBpm", str(int(track.bpm * 100)))
        track_elem.set("TotalTime", str(int(track.duration_ms / 1000)))
        
        if track.analysis_path:
            location = track.analysis_path.replace(".anlz", "").replace("/Analysis/", "/")
            if not location.startswith("file://"):
                location = "file://" + location
            track_elem.set("Location", location)
        else:
            track_elem.set("Location", "file:///unknown")
        
        if track.key:
            track_elem.set("Tonality", track.key)
        if track.genre:
            track_elem.set("Genre", track.genre)
        
        self._tracks_cache[track.id] = track_elem
        self.update_collection_entries()
        
        return track_elem

    def sync_cues_for_track(self, track: Track, cues: list[CuePoint]) -> ET.Element:
        """
        Sync cues for a track - remove old, add new.
        
        Args:
            track: Track object
            cues: List of CuePoint objects to sync
            
        Returns:
            Updated TRACK element
        """
        track_elem = self.get_or_create_track_element(track)
        
        # Remove all existing cues
        self.remove_cues_from_track(track_elem)
        
        # Add new cues
        for cue in cues:
            cue.track_id = track.id
            self.add_cue_to_track(track_elem, cue)
        
        return track_elem


def create_collection_xml(tracks: list[Track], cues_by_track: dict[int, list[CuePoint]]) -> ET.ElementTree:
    """
    Create a complete collection XML from tracks and cues.
    
    Args:
        tracks: List of Track objects
        cues_by_track: Dict mapping track_id to list of CuePoint
        
    Returns:
        ElementTree with the complete XML
    """
    writer = RekordboxXmlWriter()
    writer._create_default_structure()
    
    for track in tracks:
        track_elem = writer.create_track_element(track)
        cues = cues_by_track.get(track.id, [])
        for cue in cues:
            cue.track_id = track.id
            writer.add_cue_to_track(track_elem, cue)
    
    writer.update_collection_entries()
    return writer._tree


# Export
__all__ = ["RekordboxXmlWriter", "create_collection_xml"]
