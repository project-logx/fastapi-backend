from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean

from sqlalchemy.orm import Session, joinedload

from app.database import SessionLocal
from app.models import NodeEmbedding, Trade, TradeStatus
from app.services.embeddings import get_or_create_behavioral_profile


@dataclass
class ClusteringSample:
    trade_id: int
    embedding_id: int
    pnl: float
    vector: list[float]


def _to_utc_datetime(raw: datetime | None) -> datetime:
    if raw is None:
        return datetime.min.replace(tzinfo=UTC)
    if raw.tzinfo is None:
        return raw.replace(tzinfo=UTC)
    return raw.astimezone(UTC)


def _collect_completed_samples(db: Session, max_samples: int = 5000) -> list[ClusteringSample]:
    rows = (
        db.query(NodeEmbedding)
        .options(joinedload(NodeEmbedding.trade))
        .join(Trade, NodeEmbedding.trade_id == Trade.id)
        .filter(Trade.status == TradeStatus.COMPLETE.value)
        .order_by(Trade.closed_at.desc(), NodeEmbedding.id.desc())
        .limit(max(1, max_samples))
        .all()
    )

    samples: list[ClusteringSample] = []
    for row in rows:
        pnl = row.pnl_at_storage
        if pnl is None and row.trade is not None:
            pnl = row.trade.pnl
        if pnl is None:
            continue

        vector = row.vector or []
        if not isinstance(vector, list) or not vector:
            continue

        try:
            normalized_vector = [float(item) for item in vector]
            normalized_pnl = float(pnl)
        except (TypeError, ValueError):
            continue

        samples.append(
            ClusteringSample(
                trade_id=row.trade_id,
                embedding_id=row.id,
                pnl=normalized_pnl,
                vector=normalized_vector,
            )
        )

    if not samples:
        return []

    # Keep only vectors with the dominant dimension to avoid shape mismatch in reduction/clustering.
    dimension_counts: dict[int, int] = {}
    for sample in samples:
        dimension_counts[len(sample.vector)] = dimension_counts.get(len(sample.vector), 0) + 1
    dominant_dimension = max(dimension_counts.items(), key=lambda item: item[1])[0]
    return [sample for sample in samples if len(sample.vector) == dominant_dimension]


def _reduce_vectors(vectors: list[list[float]], n_components: int = 5) -> tuple[list[list[float]], str]:
    if not vectors:
        return [], "none"

    try:
        import numpy as np
    except ImportError:
        # Minimal fallback without numpy.
        reduced = [row[: min(3, len(row))] for row in vectors]
        return reduced, "slice-fallback-no-numpy"

    matrix = np.array(vectors, dtype=float)
    if matrix.shape[0] < 3:
        return matrix.tolist(), "identity-small-sample"

    target_components = max(2, min(n_components, matrix.shape[0] - 1, matrix.shape[1]))

    try:
        import umap  # type: ignore

        reducer = umap.UMAP(
            n_components=target_components,
            n_neighbors=max(2, min(15, matrix.shape[0] - 1)),
            min_dist=0.05,
            metric="cosine",
            random_state=42,
        )
        reduced = reducer.fit_transform(matrix)
        return reduced.tolist(), "umap"
    except Exception:
        reduced = matrix[:, :target_components]
        return reduced.tolist(), "slice-fallback"


def _cluster_reduced_vectors(reduced_vectors: list[list[float]], min_cluster_size: int = 3) -> tuple[list[int], str]:
    if not reduced_vectors:
        return [], "none"

    try:
        import numpy as np
    except ImportError:
        if len(reduced_vectors) < 2:
            return [-1 for _ in reduced_vectors], "threshold-fallback-no-numpy"
        pivot = sum(row[0] for row in reduced_vectors) / len(reduced_vectors)
        labels = [0 if row[0] >= pivot else 1 for row in reduced_vectors]
        return labels, "threshold-fallback-no-numpy"

    points = np.array(reduced_vectors, dtype=float)

    if points.shape[0] < 3:
        return [-1 for _ in reduced_vectors], "insufficient-samples"

    try:
        import hdbscan  # type: ignore

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=max(2, min(min_cluster_size, points.shape[0])),
            min_samples=max(1, min(min_cluster_size // 2, points.shape[0] - 1)),
            metric="euclidean",
        )
        labels = clusterer.fit_predict(points)
        return [int(item) for item in labels.tolist()], "hdbscan"
    except Exception:
        pivot = float(points[:, 0].mean())
        labels = [0 if float(row[0]) >= pivot else 1 for row in points]

        min_size = max(2, min(min_cluster_size, len(labels)))
        counts: dict[int, int] = {}
        for label in labels:
            counts[label] = counts.get(label, 0) + 1
        filtered = [label if counts.get(label, 0) >= min_size else -1 for label in labels]
        return filtered, "threshold-fallback"


def _compute_centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dimensions = len(vectors[0])
    centroid: list[float] = []
    for idx in range(dimensions):
        centroid.append(sum(vector[idx] for vector in vectors) / len(vectors))
    return centroid


def run_behavioral_clustering(
    db: Session,
    profile_key: str = "global",
    min_samples: int = 6,
    max_samples: int = 5000,
) -> dict:
    samples = _collect_completed_samples(db, max_samples=max_samples)
    profile = get_or_create_behavioral_profile(db, profile_key=profile_key)

    if len(samples) < max(2, min_samples):
        return {
            "status": "skipped",
            "reason": "insufficient_samples",
            "sample_count": len(samples),
            "profile_key": profile.profile_key,
            "sweet_spot_centroid": profile.sweet_spot_centroid,
            "danger_zone_centroid": profile.danger_zone_centroid,
        }

    vectors = [sample.vector for sample in samples]
    reduced_vectors, reduction_method = _reduce_vectors(vectors)
    labels, clustering_method = _cluster_reduced_vectors(reduced_vectors)

    clusters: dict[int, list[ClusteringSample]] = {}
    for index, label in enumerate(labels):
        if label < 0:
            continue
        clusters.setdefault(label, []).append(samples[index])

    if not clusters:
        return {
            "status": "skipped",
            "reason": "no_dense_clusters",
            "sample_count": len(samples),
            "profile_key": profile.profile_key,
            "reduction_method": reduction_method,
            "clustering_method": clustering_method,
            "sweet_spot_centroid": profile.sweet_spot_centroid,
            "danger_zone_centroid": profile.danger_zone_centroid,
        }

    cluster_summaries: list[dict] = []
    for label, rows in clusters.items():
        pnl_values = [row.pnl for row in rows]
        cluster_summaries.append(
            {
                "label": label,
                "count": len(rows),
                "avg_pnl": mean(pnl_values),
                "centroid": _compute_centroid([row.vector for row in rows]),
            }
        )

    positive_clusters = [item for item in cluster_summaries if item["avg_pnl"] > 0]
    negative_clusters = [item for item in cluster_summaries if item["avg_pnl"] < 0]

    sweet_cluster = max(positive_clusters, key=lambda item: item["avg_pnl"]) if positive_clusters else None
    danger_cluster = min(negative_clusters, key=lambda item: item["avg_pnl"]) if negative_clusters else None

    if sweet_cluster is None:
        positive_samples = [sample for sample in samples if sample.pnl > 0]
        if positive_samples:
            sweet_cluster = {
                "label": None,
                "avg_pnl": mean([sample.pnl for sample in positive_samples]),
                "centroid": _compute_centroid([sample.vector for sample in positive_samples]),
            }

    if danger_cluster is None:
        negative_samples = [sample for sample in samples if sample.pnl < 0]
        if negative_samples:
            danger_cluster = {
                "label": None,
                "avg_pnl": mean([sample.pnl for sample in negative_samples]),
                "centroid": _compute_centroid([sample.vector for sample in negative_samples]),
            }

    profile.sweet_spot_centroid = sweet_cluster["centroid"] if sweet_cluster else []
    profile.danger_zone_centroid = danger_cluster["centroid"] if danger_cluster else []

    return {
        "status": "completed",
        "profile_key": profile.profile_key,
        "sample_count": len(samples),
        "cluster_count": len(cluster_summaries),
        "reduction_method": reduction_method,
        "clustering_method": clustering_method,
        "sweet_spot": {
            "label": sweet_cluster["label"] if sweet_cluster else None,
            "avg_pnl": sweet_cluster["avg_pnl"] if sweet_cluster else None,
            "centroid": profile.sweet_spot_centroid,
        },
        "danger_zone": {
            "label": danger_cluster["label"] if danger_cluster else None,
            "avg_pnl": danger_cluster["avg_pnl"] if danger_cluster else None,
            "centroid": profile.danger_zone_centroid,
        },
        "clusters": [
            {
                "label": item["label"],
                "count": item["count"],
                "avg_pnl": item["avg_pnl"],
            }
            for item in sorted(cluster_summaries, key=lambda row: row["label"])
        ],
    }


def run_behavioral_clustering_job(profile_key: str = "global", min_samples: int = 6, max_samples: int = 5000) -> None:
    db = SessionLocal()
    try:
        run_behavioral_clustering(
            db=db,
            profile_key=profile_key,
            min_samples=min_samples,
            max_samples=max_samples,
        )
        db.commit()
    finally:
        db.close()
