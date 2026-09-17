## StitchScope: Trusted Recipe Resolution & Row-by-Row Validation for Photo-to-Crochet Swatches.

Photographs of crocheted fabric offer an intuitive starting point for identifying stitch patterns, but recognizing a stitch does not establish the instructions needed to reproduce it. A vision model may identify a region as filet mesh while proposing an incorrect foundation, repeat, or turning chain. StitchScope addresses this gap by separating AI identification from recipe selection and mathematical validation. The pipeline first uses Claude to identify stitch families in individual image regions, returning structured names, confidence scores, and uncertainty rather than construction instructions. Each region is then resolved independently against a schema-validated v2 recipe library through deterministic name and alias matching. Only a stored recipe whose verification status is `CONFIRMED` is eligible for user-facing instructions; model confidence, name agreement, and successful simulation cannot confer physical confirmation.

The current implementation supports independent processing of multiple image regions and repeat-based flat-swatch construction. The production v2 library remains empty pending physical confirmation, so live identification currently yields no trusted instructions. This reflects a fundamental boundary between computational and empirical validation: structural simulation can establish consistency between encoded operations and available stitch targets, but cannot verify that the resulting fabric reproduces the visual characteristics of the source image. Practical deployment therefore depends on establishing a physically confirmed recipe collection. Gauge-based sizing, garment construction, and continuous-round traversal remain outside the current scope.

For an eligible recipe, the system calculates the foundation from the requested repeat count and executes Row 1 sequentially. Each row produces an ordered, typed representation of stitch posts and chain spaces, preserving the information required for subsequent placement validation. Later rows traverse the preceding row’s output through a forward-moving cursor that enforces target-type eligibility and prevents backward access to previously passed positions. The target sequence is reversed between flat rows to represent turning the work, while repeat execution is derived from the available ordered structure. Invalid placements, insufficient targets, ambiguous resolution, and unsupported semantics prevent instruction generation. Only a successfully validated swatch plan reaches the renderer, which translates the selected library recipe into human-readable instructions using US crochet terminology.

Link to [technical documentation](docs/recipe_model_v2.md).

![StitchScope architecture: image identification, trusted recipe resolution, ordered row simulation, and instruction rendering. Failed checks produce no instructions.](docs/assets/stitchscope-pipeline.svg)

---

## Contributors

- Keziah Aba Ghartey ([@gharteykeziah](https://github.com/gharteykeziah))
