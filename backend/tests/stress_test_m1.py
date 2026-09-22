"""
PostGIS Database Concurrent Stress Test Harness for GeoPortal (Milestone 1).
Simulates 20 concurrent users executing intensive spatial queries, inter-layer joins,
and concurrent transactions to verify database performance, connection pooling,
query planner efficiency, and absence of deadlocks.
"""

import time
import random
import concurrent.futures
import psycopg2
from psycopg2.pool import ThreadedConnectionPool

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "postgres",
    "password": "postgres",
    "dbname": "geoportal",
}

NUM_WORKERS = 20
OPERATIONS_PER_WORKER = 50  # Total 1,000 concurrent operations

# Sample BBoxes in UTM Zone 36N within the dataset envelope
BBOXES = [
    (473000, 2898000, 475000, 2900000),
    (473500, 2898500, 474500, 2899500),
    (473800, 2898600, 474200, 2899000),
    (472000, 2897000, 476000, 2901000),
    (473900, 2898700, 474100, 2898900),
]


def run_worker_tasks(worker_id: int, pool: ThreadedConnectionPool) -> dict:
    stats = {
        "worker_id": worker_id,
        "queries_completed": 0,
        "errors": [],
        "total_latency_ms": 0.0,
        "max_latency_ms": 0.0,
    }

    conn = pool.getconn()
    try:
        cur = conn.cursor()
        for op in range(OPERATIONS_PER_WORKER):
            t0 = time.perf_counter()
            op_type = op % 6

            try:
                if op_type == 0:
                    # Spatial Intersection on lands
                    minx, miny, maxx, maxy = random.choice(BBOXES)
                    cur.execute("""
                        SELECT id, "Req_Number", "Area_SQM" 
                        FROM lands 
                        WHERE ST_Intersects(geom, ST_MakeEnvelope(%s, %s, %s, %s, 32636));
                    """, (minx, miny, maxx, maxy))
                    _ = cur.fetchall()

                elif op_type == 1:
                    # Spatial Containment Join between lands and points
                    cur.execute("""
                        SELECT l."Req_Number", count(p.id)
                        FROM lands l
                        JOIN points p ON ST_Contains(l.geom, p.geom)
                        WHERE l.id <= 20
                        GROUP BY l."Req_Number";
                    """)
                    _ = cur.fetchall()

                elif op_type == 2:
                    # Spatial Overlap between lands and eshghalat
                    cur.execute("""
                        SELECT l."Req_Number", e."Req_Number", ST_Area(ST_Intersection(l.geom, e.geom))
                        FROM lands l
                        JOIN eshghalat e ON ST_Intersects(l.geom, e.geom)
                        LIMIT 10;
                    """)
                    _ = cur.fetchall()

                elif op_type == 3:
                    # DWithin radius query on points using GiST index
                    cur.execute("""
                        SELECT id, "Req_Number" 
                        FROM points 
                        WHERE ST_DWithin(geom, ST_SetSRID(ST_Point(473850, 2898650), 32636), 100);
                    """)
                    _ = cur.fetchall()

                elif op_type == 4:
                    # Complex Area Aggregation and Centroid generation
                    cur.execute("""
                        SELECT count(*), sum(area_sqm), sum(area_feddan),
                               ST_AsText(ST_Centroid(ST_Collect(geom)))
                        FROM lands;
                    """)
                    _ = cur.fetchall()

                elif op_type == 5:
                    # Concurrent Transaction (Write + Read with rollback)
                    cur.execute("""
                        INSERT INTO audit_trail (table_name, record_id, action, username, created_at, timestamp)
                        VALUES ('stress_test', %s, 'STRESS_TEST', %s, NOW(), NOW())
                        RETURNING id;
                    """, (worker_id * 1000 + op, f"worker_{worker_id}"))
                    audit_id = cur.fetchone()[0]
                    # Verify read within same transaction
                    cur.execute("SELECT id, username FROM audit_trail WHERE id = %s;", (audit_id,))
                    _ = cur.fetchone()
                    # Clean up
                    cur.execute("DELETE FROM audit_trail WHERE id = %s;", (audit_id,))
                    conn.commit()

                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                stats["queries_completed"] += 1
                stats["total_latency_ms"] += elapsed_ms
                if elapsed_ms > stats["max_latency_ms"]:
                    stats["max_latency_ms"] = elapsed_ms

            except Exception as e:
                conn.rollback()
                stats["errors"].append(f"Op {op} failed: {str(e)}")

        cur.close()
    finally:
        pool.putconn(conn)

    return stats


def main():
    print(f"=== Starting PostGIS Concurrent Stress Test: {NUM_WORKERS} workers, {OPERATIONS_PER_WORKER} ops/worker ===")
    pool = ThreadedConnectionPool(minconn=5, maxconn=NUM_WORKERS + 5, **DB_CONFIG)

    wall_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = [executor.submit(run_worker_tasks, w_id, pool) for w_id in range(NUM_WORKERS)]
        results = [f.result() for f in futures]
    wall_duration = time.perf_counter() - wall_start

    pool.closeall()

    total_queries = sum(r["queries_completed"] for r in results)
    total_errors = sum(len(r["errors"]) for r in results)
    avg_latency = (
        sum(r["total_latency_ms"] for r in results) / total_queries
        if total_queries > 0 else 0
    )
    max_latency = max(r["max_latency_ms"] for r in results)
    qps = total_queries / wall_duration if wall_duration > 0 else 0

    print("\n=== Stress Test Results ===")
    print(f"Total Wall Clock Duration: {wall_duration:.3f} s")
    print(f"Total Queries Executed:    {total_queries} / {NUM_WORKERS * OPERATIONS_PER_WORKER}")
    print(f"Total Errors / Deadlocks:  {total_errors}")
    print(f"Average Query Latency:     {avg_latency:.2f} ms")
    print(f"Max Query Latency:         {max_latency:.2f} ms")
    print(f"Throughput (QPS):          {qps:.1f} queries/sec")

    if total_errors > 0:
        print("\nErrors encountered:")
        for r in results:
            for err in r["errors"]:
                print(f"  Worker {r['worker_id']}: {err}")
        return 1
    else:
        print("\nALL 20 WORKERS COMPLETED WITH ZERO ERRORS AND ZERO DEADLOCKS.")
        return 0


if __name__ == "__main__":
    exit(main())
