resource "jetstream_stream" "rasters" {
  name        = "RASTERS"
  description = "A work-queue for processing images."
  storage     = "file"
  subjects    = [
    "raster.new",
    "raster.valid",
    "raster.invalid",
    "raster.tiled",
    "chunk.new",
    "chunk.failed",
    "chunk.result",
    "result.new",
    "result.tiled"
  ]
  retention = "interest"
}

resource "jetstream_consumer" "web_index_new_raster" {
  stream_id      = jetstream_stream.rasters.id
  durable_name   = "web_index_new_raster"
  description    = "Ensures that any new image is valid and adds it to the database."
  deliver_all    = true
  ack_policy     = "explicit"
  filter_subject = "raster.new" # -> raster.valid, raster.invalid
  sample_freq    = "100"
}

resource "jetstream_consumer" "web_break_up_raster" {
  stream_id      = jetstream_stream.rasters.id
  durable_name   = "web_break_up_raster"
  description    = "Breaks up the raster into chunks for processing."
  deliver_all    = true
  ack_policy     = "explicit"
  filter_subject = "raster.valid" # -> chunk.new
  sample_freq    = "100"
}

resource "jetstream_consumer" "web_tile_raster" {
  stream_id      = jetstream_stream.rasters.id
  durable_name   = "web_tile_raster"
  description    = "Converts the raster into a standardised form for tiled maps."
  deliver_all    = true
  ack_policy     = "explicit"
  filter_subject = "raster.valid" # -> raster.tiled
  sample_freq    = "100"
}

resource "jetstream_consumer" "web_catch_invalid_rasters" {
  stream_id      = jetstream_stream.rasters.id
  durable_name   = "web_catch_invalid_rasters"
  description    = "Marks invalid rasters in the database."
  deliver_all    = true
  ack_policy     = "explicit"
  filter_subject = "raster.invalid" # -> done
  sample_freq    = "100"
}

resource "jetstream_consumer" "predictor_process_chunks" {
  stream_id      = jetstream_stream.rasters.id
  durable_name   = "predictor_process_chunks"
  description    = "Takes chunks of an image and runs it through the model."
  deliver_all    = true
  ack_policy     = "explicit"
  filter_subject = "chunk.new" # -> chunk.result, chunk.failed
  ack_wait       = "3600"
  sample_freq    = "100"
}

resource "jetstream_consumer" "predictor_delete_temp_file" {
  stream_id      = jetstream_stream.rasters.id
  durable_name   = "predictor_delete_temp_file"
  description    = "Record of temporary files for deletion"
  deliver_all    = true
  ack_policy     = "explicit"
  filter_subject = "result.tiled"
  sample_freq    = "100"
}

resource "jetstream_consumer" "web_record_chunk_result" {
  stream_id      = jetstream_stream.rasters.id
  durable_name   = "web_record_chunk_result"
  description    = "Records the results of processing each chunk."
  deliver_all    = true
  ack_policy     = "explicit"
  filter_subject = "chunk.result" # -> result.new
  sample_freq    = "100"
}

resource "jetstream_consumer" "web_catch_failed_chunks" {
  stream_id      = jetstream_stream.rasters.id
  durable_name   = "web_catch_failed_chunks"
  description    = "Records the failure of a chunk."
  deliver_all    = true
  ack_policy     = "explicit"
  filter_subject = "chunk.failed" # -> result.new
  sample_freq    = "100"
}

resource "jetstream_consumer" "web_write_results" {
  stream_id      = jetstream_stream.rasters.id
  durable_name   = "web_write_results"
  description    = "Writes the results of the model to the final file."
  deliver_all    = true
  ack_policy     = "explicit"
  filter_subject = "result.new" # -> result.tiled
  ack_wait       = 3600
  sample_freq    = "100"
}

resource "jetstream_consumer" "web_delete_temp_file" {
  stream_id      = jetstream_stream.rasters.id
  durable_name   = "web_delete_temp_file"
  description    = "Record for temp files for deletion from web"
  deliver_all    = true
  ack_policy     = "explicit"
  filter_subject = "result.tiled"
  sample_freq    = "100"
}