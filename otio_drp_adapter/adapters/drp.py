import json
import opentimelineio as otio
from os.path import basename


"""
Adapter to read (and ultimately write) a .drp file generated by the
Blackmagic Design ATEM ISO mixer, aimed at DaVinci's timeline format.

File is JSON-based, line-delimited.
First line includes the metadata and sources in a JSON hash,
Next lines describes the scene switches until the show ends.

Careful: this .drp file format might not be exactly compatible with DaVinci,
as the Blackmagic ATEM ISO may generate a simplified version, and there
doesn't seem to be any easy to find reference specifications for those files.

"""


def read_from_file(filepath):
    # We read the .drp file directly
    with open(filepath) as source:
        # First line contains metadata and the starting settings
        metadata = json.loads(source.readline().strip())

        # Next ones are the scene switches, let's decode them right away
        timeline_data = []
        for line in source:
            timeline_data += [json.loads(line.strip())]
        # We use the filename as the timeline name (without the .drp suffix)
        timeline_name = basename(filepath[:-4])
        track_name = "Main Mix"
        timeline = otio.schema.Timeline(timeline_name)
        # We will use the masterTimecode as a 0 reference
        mt = metadata["masterTimecode"]
        # BlackMagic's ATEM seems to be only 1080p25, but well
        widths, rates = metadata["videoMode"].split("p")
        rate = int(rates)
        # For now, the timeline is a single track.
        track = otio.schema.Track(track_name)
        timeline.tracks.append(track)
        # If we don't have sources, the .drp file is probably broken.
        if "sources" not in metadata:
            raise Exception("No sources in drp file")

        tc_ref = otio.opentime.from_timecode(mt, rate)
        current_tc = otio.opentime.RationalTime(value=0, rate=rate)
        # Let's compute the duration of the full scene based on the last switch
        last_tc = timeline_data[-1]["masterTimecode"]
        end_frame = otio.opentime.from_timecode(last_tc, rate)
        duration = end_frame - tc_ref
        # And make it available for the ext ref
        available_range = otio.opentime.TimeRange(
            start_time=current_tc,
            duration=duration,
        )

        # Let's create an hash with all the indices as the key for later
        # and create the external reference for the files
        # (it may be more clever to generate one for each source)
        extrefs = dict()
        for src in metadata["sources"]:
            src["ref"] = None
            # If it's an actual file, generate a ref for it
            if "file" in src:
                ref = otio.schema.ExternalReference(
                    target_url=src["file"], available_range=available_range
                )
                # add it to the src dict from JSON
                src["ref"] = ref
            # add our entry to extrefs, with _index_ as the key (it's an int.)
            extrefs[src["_index_"]] = src

        # Loosely try to get the scene chosen before the show starts
        try:
            current_source = metadata["mixEffectBlocks"][0]["source"]
        except KeyError:
            current_source = 0

        # Let's loop over the switches in the timeline
        for c in timeline_data:
            # End of current clip is there, and it has that many frames
            next_clip_tc = otio.opentime.from_timecode(c["masterTimecode"], rate)
            next_clip_frames = next_clip_tc - tc_ref

            # So let's figure out its name and ext ref from our hash
            # and compute its length in frames
            clip = otio.schema.Clip(
                extrefs[current_source]["name"],
                media_reference=extrefs[current_source]["ref"],
                source_range=otio.opentime.TimeRange(
                    current_tc,
                    next_clip_frames,
                ),
            )
            # Add it to the track
            track.append(clip)
            # Prepare for the next round, let's move on at the end
            # of the added clip, and set the sources for the next clip.
            current_tc += next_clip_frames
            if "source" in c["mixEffectBlocks"][0]:
                current_source = c["mixEffectBlocks"][0]["source"]
            else:
                break

    return timeline
