import os
import tempfile
import unittest
import zipfile
from .base import TrackMetadata, ReleaseMetadata
from .routenote import RouteNoteConnector


class SecurityTests(unittest.TestCase):
    def test_tracks_csv_neutralizes_formula_fields(self):
        meta = ReleaseMetadata(
            title="=HYPERLINK(\"https://example.invalid\", \"Album\")",
            primary_artist="@ATTACK",
            tracks=[TrackMetadata(
                title=" =HYPERLINK(\"https://attacker.invalid\",\"Open\")",
                artist="+cmd|' /C calc'!A0",
                language="-2",
                track_number=1,
            )],
        )
        with tempfile.TemporaryDirectory() as audio_dir, tempfile.TemporaryDirectory() as out_dir:
            audio = os.path.join(audio_dir, "track.mp3")
            artwork = os.path.join(audio_dir, "artwork.jpg")
            open(audio, "wb").close()
            open(artwork, "wb").close()
            package = RouteNoteConnector().build_package(
                "securitytest", meta, [audio], artwork, out_dir
            )
            with zipfile.ZipFile(package) as z:
                csv_text = z.read("tracks.csv").decode()
        self.assertIn("' =HYPERLINK", csv_text)
        self.assertIn("'+cmd|' /C calc'!A0", csv_text)
        self.assertIn("'-2", csv_text)


if __name__ == "__main__":
    unittest.main()
