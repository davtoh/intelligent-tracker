.. _scenario_studio:

World Scenario Studio, Space Awareness & Ground Plane Homography
================================================================

The **Scenario Studio & Spatial Awareness** subsystem (Milestone 8) elevates Intelligent Tracker
from single-view video analysis into a multi-camera, metric 3D space-aware intelligence platform.
It empowers security operators, facility managers, and retail analysts to interactively map physical environments,
model multi-camera transit topology, project contact coordinates into top-down metric space, and reconstruct
comprehensive entity journeys.

System Architecture
-------------------

.. code-block:: text

    +-----------------------------------------------------------------------------------------------+
    |                                   Interactive Scenario Studio                                 |
    |  - Canvas Polygonal Zone Tool (Click vertices, close polygon, dwell threshold & capacity)     |
    |  - Directional Tripwire Tool (Click 2 points, IN/OUT normal vectors, bidirectional toggle)    |
    |  - 4-Point Homography Calibration Tool (Select 4 ground corners -> define metric W x H)       |
    |  - Cross-Camera Topology Links (Connect Camera A exit zone -> Camera B entrance zone)         |
    |  - Floating Overlay Control Toolbar (Toggle BBoxes, IDs, Dwell, Velocity, Zones, Minimap, HUD)|
    +-----------------------------------------------------------------------------------------------+
                                  |                                             |
                  REST Endpoints & WebSocket Sync                  Dual Persistence
                                  |                                             |
                                  v                                             v
    +-------------------------------------------------------------+   +-----------------------------+
    |                      ScenarioManager                        |   |  - configs/scenarios.yaml   |
    |  - In-Memory Spatial Geometry Cache                         |   |  - SQLite TrackerDB:        |
    |  - Hot Pipeline Injection into Active StreamManager         |   |    * spatial_zones          |
    |  - Top-down BEV Minimap Renderer                            |   |    * spatial_tripwires      |
    +-------------------------------------------------------------+   |    * spatial_transitions    |
            |                               |                         |    * homography_calibrations|
            v                               v                         +-----------------------------+
    +-----------------------+   +-----------------------------+
    | GroundPlaneHomography |   |    CrossCameraTopology      |
    |  - 4-Point cv2 Matrix |   |  - Transit Windows [Tmin,Tmax]
    |  - Contact: (x+w/2,y+h)|   |  - Predictive Spatial Priors|
    |  - Metric (X,Y) in m  |   |  - Bayesian Re-ID Prior Boost|
    +-----------------------+   +-----------------------------+
            |                               |
            v                               v
    +-----------------------+   +-----------------------------+
    |   BEV Top-Down Canvas |   | Trajectory Journey Engine   |
    |  - Metric Grid (meters)|   |  - Multi-Camera Hop Slicing |
    |  - Zones & Boundaries |   |  - Transit Delay Analysis   |
    |  - Kinematic Vectors  |   |  - MP4 Video Compilation    |
    +-----------------------+   +-----------------------------+

Key Capabilities
----------------

1. Interactive In-Browser Scenario Studio
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Operators can visually configure computer vision spatial logic directly over live video frames:

- **Polygonal Zones**: Click any sequence of vertices to outline loitering zones, restricted vaults, or queue lines.
  Configure custom dwell time thresholds, capacity limits, category filters (e.g. ``visitor`` vs ``staff``), and hex/RGB colors.
- **Directional Tripwires**: Place two-point tripwire lines with calculated IN/OUT normal direction indicators,
  bidirectional tracking toggles, and line crossing counters.
- **Real-Time Hot Injection**: Modifications are dispatched via REST and instantly updated in active
  ``StreamManager.analytics`` engines without dropping video frames or disconnecting clients.

2. 4-Point Ground Plane Homography & BEV Minimap
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Camera feeds suffer from severe perspective foreshortening. Intelligent Tracker computes planar projective
homography to translate camera pixels into metric ground coordinates:

**Mathematical Formulation:**

Given four non-collinear source points in image space :math:`P_{src} = [(x_i, y_i)]_{i=1}^4` and corresponding
metric ground plane points :math:`P_{dst} = [(X_i, Y_i)]_{i=1}^4`, the 3x3 homography matrix :math:`H` satisfies:

.. math::

    s \begin{bmatrix} X \\ Y \\ 1 \end{bmatrix} = H \begin{bmatrix} x \\ y \\ 1 \end{bmatrix} =
    \begin{bmatrix}
    h_{11} & h_{12} & h_{13} \\
    h_{21} & h_{22} & h_{23} \\
    h_{31} & h_{32} & h_{33}
    \end{bmatrix}
    \begin{bmatrix} x \\ y \\ 1 \end{bmatrix}

The Euclidean coordinates on the metric ground plane are:

.. math::

    X = \frac{h_{11}x + h_{12}y + h_{13}}{h_{31}x + h_{32}y + h_{33}}, \quad
    Y = \frac{h_{21}x + h_{22}y + h_{23}}{h_{31}x + h_{32}y + h_{33}}

- **Contact Point Mapping**: Tracks are projected onto the ground plane using their bottom-center contact point
  :math:`(x + w/2, y + h)`.
- **2D Top-Down Minimap Canvas**: Renders a dark-themed tactical Bird's-Eye-View (BEV) minimap complete with metric grid lines,
  zone polygon outlines, track markers, velocity vectors, and entity names.
- **Picture-in-Picture (PiP) Stream**: The BEV minimap can be overlaid directly into the live video stream or fetched
  independently via ``/api/scenarios/bev/{camera_id}``.

3. Cross-Camera Topological Space Awareness
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Realizes the high-level domain abstractions (``Scene``, ``Area``, ``Line``) across distributed camera feeds:

- **Spatial Transition Links**: Define physical pathways connecting cameras (e.g. ``cam_01[Door Exit] -> cam_02[Door Entrance]``).
- **Transit Time Windows**: Specify minimum :math:`T_{min}` and maximum :math:`T_{max}` expected transit seconds.
- **Predictive Spatial Priors**: When an entity exits a source zone, an ``ActiveSpatialPrior`` is automatically spawned
  for the destination camera.
- **Bayesian Re-ID Prior Boosting**: If an entity appears in the destination zone during :math:`[t_{exit} + T_{min}, t_{exit} + T_{max}]`,
  its Re-ID similarity score is boosted:

  .. math::

      S_{final} = \min(1.0, S_{visual} + \text{prior\_boost})

  This topological prior eliminates identity swapping across multi-camera handoffs, even when candidates wear similar clothing.

4. Trajectory Journey Search & Video Exporter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Security investigators can reconstruct full chronological journeys across all cameras:

- **Chronological Hop Segmentation**: Sightings from TrackerDB are aggregated into discrete camera hops with dwell durations
  and inter-camera transit times (e.g. *10:02 CAM_01 (Front Gate) [10s] -> 10:04 CAM_02 (Lobby Front) [15s]*).
- **One-Click MP4 Journey Export**: Slices recorded camera clips or synthesizes an animated tactical video summary complete
  with timestamp title cards, camera badges, and bounding box highlights into a downloadable MP4 file.

5. Customizable & Removable Video Overlays
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A floating overlay control toolbar on the live monitor enables operators to independently toggle:

- Bounding Boxes (``bboxes``)
- Track IDs & Entity Names (``track_ids``)
- Loitering Dwell Timers (``dwell_timers``)
- Kinematic Velocity Vectors (``velocity``)
- Polygonal Zones (``zones``)
- Directional Tripwires (``tripwires``)
- Spatial Density Heatmap (``heatmap``)
- BEV Top-Down Minimap (``bev_minimap``)
- Tactical HUD Status Bar (``hud_bar``)

REST API Endpoints
------------------

.. list-table::
   :widths: 20 35 45
   :header-rows: 1

   * - Method
     - Endpoint
     - Description
   * - ``GET``
     - ``/api/scenarios``
     - Retrieve all camera zones, tripwires, homography, and topology links.
   * - ``GET``
     - ``/api/scenarios/{camera_id}``
     - Retrieve spatial scenario configuration for a single camera.
   * - ``POST``
     - ``/api/scenarios/zones``
     - Create or update a polygonal zone (persisting to YAML and SQLite).
   * - ``DELETE``
     - ``/api/scenarios/zones/{cam}/{name}``
     - Delete a zone from memory, YAML, and SQLite.
   * - ``POST``
     - ``/api/scenarios/tripwires``
     - Create or update a directional tripwire line.
   * - ``DELETE``
     - ``/api/scenarios/tripwires/{cam}/{name}``
     - Delete a tripwire line.
   * - ``POST``
     - ``/api/scenarios/homography``
     - Calibrate 4-point ground plane perspective matrix and metric dimensions.
   * - ``GET``
     - ``/api/scenarios/homography/{camera_id}``
     - Retrieve homography calibration profile.
   * - ``DELETE``
     - ``/api/scenarios/homography/{camera_id}``
     - Reset homography calibration for a camera.
   * - ``GET``
     - ``/api/scenarios/bev/{camera_id}``
     - Fetch real-time JPEG top-down Bird's-Eye-View minimap image.
   * - ``GET``
     - ``/api/topology/transitions``
     - List registered cross-camera spatial transition links.
   * - ``POST``
     - ``/api/topology/transitions``
     - Create a cross-camera transition link with transit windows and prior boost.
   * - ``DELETE``
     - ``/api/topology/transitions/{link_id}``
     - Delete a spatial transition link.
   * - ``GET``
     - ``/api/topology/priors``
     - List live active spatial priors.
   * - ``GET``
     - ``/api/journey/search``
     - Search multi-camera trajectory hops and transit duration narrative.
   * - ``POST``
     - ``/api/journey/export``
     - Compile and export an MP4 journey summary video.
   * - ``GET``
     - ``/api/cameras/{camera_id}/overlays``
     - Retrieve overlay visibility flags.
   * - ``POST``
     - ``/api/cameras/{camera_id}/overlays``
     - Dynamically toggle overlay elements.

Declarative Configuration Example
---------------------------------

Below is an excerpt from ``configs/scenarios.yaml``:

.. code-block:: yaml

    version: "1.0"
    cameras:
      cam_01:
        zones:
          - name: "Door Exit"
            polygon: [[100, 100], [250, 100], [250, 300], [100, 300]]
            dwell_threshold: 3.0
            category_filter: "person"
            color: [0, 200, 100]
        tripwires:
          - name: "Entrance Tripwire"
            line_segment: [[50, 200], [300, 200]]
            bidirectional: true
            color: [0, 255, 255]
        homography:
          is_calibrated: true
          metric_width: 10.0
          metric_height: 15.0
          src_points: [[100, 100], [500, 100], [600, 400], [0, 400]]
          dst_points: [[0, 0], [10, 0], [10, 15], [0, 15]]

    spatial_transitions:
      - link_id: "cam01_door_to_cam02_entrance"
        source_camera: "cam_01"
        source_zone: "Door Exit"
        target_camera: "cam_02"
        target_zone: "Door Entrance"
        t_min: 2.0
        t_max: 15.0
        prior_boost: 0.35
        bidirectional: false
        active: true
