# HDR JPEG input compatibility

The input contract remains JPEG/PNG, 10 MiB per file, 20,000,000 pixels.
This change accepts the specific Apple HDR auxiliary JPEG profile reproduced in
30 local phone images: two contiguous MPF-indexed JPEG images, a primary image
and a grayscale gain map with Apple AuxiliaryImageType and HDRGainMapVersion
131072 XMP metadata. Generic MPO, other gain-map profiles, animation, malformed
MPF/XMP, extra images and trailing data are not enabled by this change.

Only the primary image is passed through the existing EXIF transpose and RGB
conversion to the model. The auxiliary image is bounded and decoded to validate
it, but never used for inference. The backend preserves original bytes and hash.
Both implementations run the identical synthetic fixture matrix in
`tests/fixtures/cases.tsv` / Backend `src/test/resources/images/cases.tsv`.
No user photos are included in these fixtures. The fixture primary is red,
32x24, EXIF orientation 6; its grayscale auxiliary is 16x12. The expected model
input is red RGB 24x32. The fixture includes no personal metadata.

Run `python -B -m unittest discover -s tests -v`. The API tests use a fake engine
at the model boundary; actual-model validation must be performed separately.

Deploy inference before enabling this format in Backend; roll back Backend
before inference. Model weights, thresholds, runtime secrets and network
configuration do not change.
