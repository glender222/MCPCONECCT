"""
Unit tests for BibTeX and CSV Exporters.
"""
from exporters.bibtex_exporter import BibtexExporter
from exporters.csv_exporter import CsvExporter


SAMPLE_PAPERS = [
    {
        "title": "Unlearnable Examples: Making Personal Data Unexploitable",
        "authors": ["Hanxun Huang", "Xingjun Ma", "Sarah Monazam Erfani", "James Bailey", "Yisen Wang"],
        "year": "2021",
        "doi": "10.1109/ICCV48922.2021.00880",
        "venue": "IEEE/CVF International Conference on Computer Vision (ICCV)",
        "doc_type": "Conference Paper",
        "abstract": "Deep learning models require massive amounts of data for training...",
        "url": "https://doi.org/10.1109/ICCV48922.2021.00880",
        "citation_count": 350,
        "database": "IEEE Xplore",
    },
    {
        "title": "Availability Attacks Create Shortcuts in Deep Neural Networks",
        "authors": ["Chuan Guo", "Alexandre Sablayrolles", "Herve Jegou", "Douwe Kiela"],
        "year": "2022",
        "doi": "10.1038/s41467-022-12345-6",
        "venue": "Nature Communications",
        "doc_type": "Article",
        "abstract": "We show that availability attacks introduce robust shortcut features...",
        "url": "https://doi.org/10.1038/s41467-022-12345-6",
        "citation_count": 180,
        "database": "Scopus",
    }
]


def test_bibtex_export():
    bibtex = BibtexExporter.export(SAMPLE_PAPERS)
    assert "@inproceedings{" in bibtex
    assert "@article{" in bibtex
    assert "Unlearnable Examples" in bibtex
    assert "10.1109/ICCV48922.2021.00880" in bibtex
    assert "Nature Communications" in bibtex


def test_csv_export():
    csv_str = CsvExporter.export(SAMPLE_PAPERS)
    lines = csv_str.strip().split("\n")
    assert len(lines) == 3  # Header + 2 papers
    assert "DOI,Title,Authors,Year" in lines[0].replace('"', '')
    assert "10.1109/ICCV48922.2021.00880" in lines[1]
    assert "Availability Attacks" in lines[2]
