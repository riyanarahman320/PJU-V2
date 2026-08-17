"""Menyimpulkan rentang Population_Density dari ambang split pohon RF.

MENGAPA PERLU
-------------
Pipeline memakai 'passthrough' untuk fitur numerik: tidak ada scaler. Karena
itu satuan Population_Density yang dikirim HARUS sama dengan dataset training.
Dataset itu tidak ada di project, jadi satuannya tidak dapat dibaca langsung.

RandomForest tidak menyimpan data training, tetapi setiap split menyimpan
ambang numerik. Kumpulan ambang pada kolom Population_Density berada di dalam
rentang nilai yang benar-benar dilihat model saat training. Itu cukup untuk
mengetahui skalanya: ratusan (ribu jiwa/km2) atau puluhan ribu (jiwa/km2).

CATATAN: ini INFERENSI, bukan pembacaan dataset. Hasilnya menunjukkan rentang
yang dikenal model, bukan angka sebenarnya untuk suatu titik PJU.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TARGET = "Population_Density"


def main() -> int:
    from backend.services.ai import model_loader

    status = model_loader.model_status()
    if status["status"] == "ERROR":
        print(f"Model tidak dapat dimuat: {status['error']}")
        return 1

    pipeline = model_loader.get_rf_pipeline()

    # Cari langkah berdasarkan kemampuannya, bukan namanya, supaya tidak
    # bergantung pada penamaan di dalam pickle.
    pre = None
    clf = None
    for step in (getattr(pipeline, "named_steps", {}) or {}).values():
        if hasattr(step, "transformers_"):
            pre = step
        if hasattr(step, "estimators_"):
            clf = step

    if pre is None or clf is None:
        print("Struktur pipeline tidak seperti yang diharapkan.")
        print(f"langkah: {[(n, type(s).__name__) for n, s in pipeline.steps]}")
        return 1

    # Cari posisi kolom Population_Density SETELAH transformasi.
    try:
        nama_keluaran = list(pre.get_feature_names_out())
    except Exception as exc:  # noqa: BLE001
        print(f"Tidak dapat membaca nama fitur keluaran: {exc}")
        return 1

    indeks = [i for i, n in enumerate(nama_keluaran) if TARGET in n]
    if not indeks:
        print(f"Kolom {TARGET} tidak ditemukan pada keluaran preprocessor.")
        print(f"Nama keluaran: {nama_keluaran}")
        return 1

    kolom = indeks[0]
    print(f"{TARGET} -> kolom hasil transformasi ke-{kolom} "
          f"('{nama_keluaran[kolom]}')")
    print(f"jumlah pohon: {len(clf.estimators_)}")

    ambang = []
    for tree in clf.estimators_:
        t = tree.tree_
        for node in range(t.node_count):
            if t.children_left[node] == -1:  # daun
                continue
            if t.feature[node] == kolom:
                ambang.append(float(t.threshold[node]))

    if not ambang:
        print("Tidak ada split pada kolom ini; model tidak memakainya.")
        return 0

    ambang.sort()
    n = len(ambang)

    def persentil(p: float) -> float:
        return ambang[min(n - 1, max(0, int(p * n)))]

    print(f"\njumlah split pada {TARGET}: {n}")
    print(f"minimum ambang : {ambang[0]:,.2f}")
    print(f"persentil 1    : {persentil(0.01):,.2f}")
    print(f"median         : {persentil(0.50):,.2f}")
    print(f"persentil 99   : {persentil(0.99):,.2f}")
    print(f"maksimum ambang: {ambang[-1]:,.2f}")

    print("\nKESIMPULAN SKALA")
    puncak = ambang[-1]
    if puncak < 1000:
        print("  Nilai training tampaknya dalam RIBU JIWA/km2 atau satuan")
        print("  lain berskala ratusan. Mengirim 12000 akan jauh di luar")
        print("  rentang yang dikenal model.")
    elif puncak < 100000:
        print("  Nilai training tampaknya JIWA/km2 mentah (puluhan ribu).")
        print(f"  Rentang aman kira-kira {ambang[0]:,.0f} - {puncak:,.0f}.")
    else:
        print("  Skala sangat besar; periksa ulang satuan dataset.")

    print("\nPERINGATAN: ini inferensi dari ambang split, BUKAN dataset asli.")
    print("Nilai untuk titik PJU sungguhan tetap harus berasal dari data BPS")
    print("atau sumber resmi lain, bukan dari angka yang dikarang.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
