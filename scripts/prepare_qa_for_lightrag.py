#!/usr/bin/env python3
"""
QA Data Preparation Script for LightRAG
Converts qa_log.jsonl into LightRAG-ready document format.

Features:
- Groups similar questions by first 3 significant words
- Handles Russian text with proper normalization
- Generates LightRAG-compatible document format
- Provides comprehensive statistics and progress tracking
- Robust error handling for production use
"""

import json
import re
import logging
from datetime import datetime
from pathlib import Path
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Set
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('qa_processing.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class QAProcessor:
    """Processes QA logs and prepares them for LightRAG ingestion."""

    def __init__(self, input_file: str = "logs/qa_log.jsonl", output_file: str = "ready_for_lightrag.txt"):
        self.input_file = Path(input_file)
        self.output_file = Path(output_file)

        # Russian stop words to skip when creating group keys
        self.stop_words: Set[str] = {
            'как', 'что', 'где', 'когда', 'почему', 'зачем', 'какой', 'какая',
            'какие', 'какую', 'каких', 'кто', 'чем', 'при', 'для', 'про', 'об',
            'в', 'на', 'с', 'у', 'из', 'к', 'по', 'от', 'до', 'за', 'над',
            'под', 'между', 'через', 'при', 'без', 'кроме', 'вместо',
            'это', 'тот', 'та', 'те', 'этот', 'эта', 'эти', 'который', 'которая'
        }

        # Statistics tracking
        self.stats = {
            'total_lines_processed': 0,
            'valid_qa_pairs': 0,
            'malformed_lines': 0,
            'groups_created': 0,
            'avg_questions_per_group': 0,
            'processing_time': 0,
            'duplicates_removed': 0
        }

        # Grouped Q&A data
        self.qa_groups: Dict[str, List[Dict]] = defaultdict(list)

    def normalize_question(self, question: str) -> str:
        """
        Normalize Russian question text for grouping.

        Args:
            question: Raw question text

        Returns:
            Normalized key for grouping (first 3 significant words)
        """
        if not question or not question.strip():
            return "пустой_вопрос"

        # Clean and normalize text
        text = question.lower().strip()

        # Remove punctuation and extra spaces
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text)

        # Split into words and filter out stop words
        words = [word for word in text.split() if word and word not in self.stop_words]

        # Handle short questions
        if len(words) == 0:
            return "общий_вопрос"
        elif len(words) == 1:
            return words[0]
        elif len(words) == 2:
            return '_'.join(words)
        else:
            # Take first 3 significant words
            return '_'.join(words[:3])

    def load_qa_data(self) -> None:
        """Load and parse QA data from JSONL file."""

        if not self.input_file.exists():
            logger.error(f"Input file not found: {self.input_file}")
            raise FileNotFoundError(f"QA log file not found: {self.input_file}")

        logger.info(f"Loading QA data from: {self.input_file}")

        start_time = datetime.now()

        try:
            with open(self.input_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    self.stats['total_lines_processed'] += 1

                    # Show progress for large files
                    if line_num % 100 == 0:
                        logger.info(f"Processed {line_num} lines...")

                    line = line.strip()
                    if not line:
                        continue

                    try:
                        # Parse JSON line
                        qa_entry = json.loads(line)

                        # Validate required fields
                        if not self._validate_qa_entry(qa_entry):
                            self.stats['malformed_lines'] += 1
                            continue

                        # Extract and normalize question
                        question = qa_entry.get('question', '').strip()
                        answer = qa_entry.get('answer', '').strip()

                        if not question or not answer:
                            self.stats['malformed_lines'] += 1
                            logger.warning(f"Line {line_num}: Missing question or answer")
                            continue

                        # Generate group key
                        group_key = self.normalize_question(question)

                        # Check for exact duplicates within group
                        if self._is_duplicate(group_key, question, answer):
                            self.stats['duplicates_removed'] += 1
                            continue

                        # Add to group
                        self.qa_groups[group_key].append({
                            'question': question,
                            'answer': answer,
                            'timestamp': qa_entry.get('timestamp', ''),
                            'user_id': qa_entry.get('user_id', ''),
                            'processing_time_ms': qa_entry.get('processing_time_ms', 0)
                        })

                        self.stats['valid_qa_pairs'] += 1

                    except json.JSONDecodeError as e:
                        self.stats['malformed_lines'] += 1
                        logger.warning(f"Line {line_num}: Invalid JSON - {e}")
                        continue
                    except Exception as e:
                        self.stats['malformed_lines'] += 1
                        logger.warning(f"Line {line_num}: Processing error - {e}")
                        continue

        except Exception as e:
            logger.error(f"Error reading input file: {e}")
            raise

        # Calculate final statistics
        self.stats['groups_created'] = len(self.qa_groups)
        if self.stats['groups_created'] > 0:
            self.stats['avg_questions_per_group'] = round(
                self.stats['valid_qa_pairs'] / self.stats['groups_created'], 2
            )

        self.stats['processing_time'] = (datetime.now() - start_time).total_seconds()

        logger.info(f"✅ Data loading completed in {self.stats['processing_time']:.2f}s")

    def _validate_qa_entry(self, entry: dict) -> bool:
        """Validate that QA entry has required fields."""
        required_fields = ['question', 'answer']
        return all(field in entry for field in required_fields)

    def _is_duplicate(self, group_key: str, question: str, answer: str) -> bool:
        """Check if this Q&A pair already exists in the group."""
        if group_key not in self.qa_groups:
            return False

        for existing in self.qa_groups[group_key]:
            if (existing['question'].lower().strip() == question.lower().strip() and
                existing['answer'].lower().strip() == answer.lower().strip()):
                return True
        return False

    def format_for_lightrag(self) -> str:
        """
        Format grouped Q&A data for LightRAG ingestion.

        Returns:
            Formatted document string ready for LightRAG
        """
        logger.info("Formatting data for LightRAG...")

        # Generate timestamp
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")

        # Start document
        document_lines = [
            f"Часто задаваемые вопросы [сгенерировано {timestamp}]",
            "",
            f"Обработано {self.stats['valid_qa_pairs']} пар вопрос-ответ, "
            f"сгруппировано в {self.stats['groups_created']} категорий.",
            "",
            "=" * 70,
            ""
        ]

        # Sort groups by frequency (most questions first)
        sorted_groups = sorted(
            self.qa_groups.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )

        group_num = 0
        for group_key, qa_pairs in sorted_groups:
            group_num += 1

            # Add group header
            group_name = self._generate_group_name(group_key, qa_pairs)
            document_lines.extend([
                f"## Категория {group_num}: {group_name}",
                f"({len(qa_pairs)} вопрос{'ов' if len(qa_pairs) != 1 else ''})",
                ""
            ])

            # Sort Q&A pairs within group by recency (newest first)
            sorted_qa = sorted(
                qa_pairs,
                key=lambda x: x.get('timestamp', ''),
                reverse=True
            )

            # Add each Q&A pair
            for qa in sorted_qa:
                document_lines.extend([
                    f"Вопрос: {qa['question']}",
                    f"Ответ: {qa['answer']}",
                    "---",
                    ""
                ])

        # Add footer with processing statistics
        document_lines.extend([
            "=" * 70,
            "",
            "Статистика обработки:",
            f"• Всего обработано строк: {self.stats['total_lines_processed']}",
            f"• Валидных Q&A пар: {self.stats['valid_qa_pairs']}",
            f"• Некорректных строк пропущено: {self.stats['malformed_lines']}",
            f"• Дубликатов удалено: {self.stats['duplicates_removed']}",
            f"• Создано групп: {self.stats['groups_created']}",
            f"• Среднее вопросов на группу: {self.stats['avg_questions_per_group']}",
            f"• Время обработки: {self.stats['processing_time']:.2f} сек",
            "",
            f"Документ готов для загрузки в LightRAG - {timestamp}"
        ])

        return '\n'.join(document_lines)

    def _generate_group_name(self, group_key: str, qa_pairs: List[Dict]) -> str:
        """Generate a human-readable name for the group."""

        # Clean up the group key
        words = group_key.replace('_', ' ').split()

        # Capitalize first letters
        readable_name = ' '.join(word.capitalize() for word in words)

        # Add context based on common question patterns
        if any('настр' in qa['question'].lower() for qa in qa_pairs):
            readable_name += " (Настройка)"
        elif any('ошибк' in qa['question'].lower() for qa in qa_pairs):
            readable_name += " (Ошибки)"
        elif any('установ' in qa['question'].lower() for qa in qa_pairs):
            readable_name += " (Установка)"
        elif any('подключ' in qa['question'].lower() for qa in qa_pairs):
            readable_name += " (Подключение)"

        return readable_name

    def save_document(self, document: str) -> None:
        """Save formatted document to output file."""

        logger.info(f"Saving document to: {self.output_file}")

        try:
            # Create output directory if needed
            self.output_file.parent.mkdir(parents=True, exist_ok=True)

            # Write document with UTF-8 encoding
            with open(self.output_file, 'w', encoding='utf-8') as f:
                f.write(document)

            logger.info(f"✅ Document saved successfully: {self.output_file}")
            logger.info(f"📄 File size: {self.output_file.stat().st_size:,} bytes")

        except Exception as e:
            logger.error(f"❌ Error saving document: {e}")
            raise

    def print_statistics(self) -> None:
        """Print comprehensive processing statistics."""

        print("\n" + "=" * 70)
        print("🏁 QA PROCESSING STATISTICS")
        print("=" * 70)

        print(f"📊 Input Processing:")
        print(f"   • Total lines read: {self.stats['total_lines_processed']:,}")
        print(f"   • Valid Q&A pairs: {self.stats['valid_qa_pairs']:,}")
        print(f"   • Malformed lines skipped: {self.stats['malformed_lines']:,}")
        print(f"   • Duplicates removed: {self.stats['duplicates_removed']:,}")

        print(f"\n📋 Grouping Results:")
        print(f"   • Groups created: {self.stats['groups_created']:,}")
        print(f"   • Average Q&A per group: {self.stats['avg_questions_per_group']}")

        # Top 10 largest groups
        if self.qa_groups:
            print(f"\n🔝 Top 10 Question Categories:")
            sorted_groups = sorted(
                self.qa_groups.items(),
                key=lambda x: len(x[1]),
                reverse=True
            )[:10]

            for i, (group_key, qa_pairs) in enumerate(sorted_groups, 1):
                group_name = self._generate_group_name(group_key, qa_pairs)
                print(f"   {i:2d}. {group_name}: {len(qa_pairs)} вопрос{'ов' if len(qa_pairs) != 1 else ''}")

        print(f"\n⏱️ Performance:")
        print(f"   • Processing time: {self.stats['processing_time']:.2f} seconds")

        if self.stats['processing_time'] > 0:
            qps = self.stats['valid_qa_pairs'] / self.stats['processing_time']
            print(f"   • Processing rate: {qps:.1f} Q&A pairs/second")

        print(f"\n📁 Output:")
        print(f"   • Output file: {self.output_file}")
        if self.output_file.exists():
            print(f"   • File size: {self.output_file.stat().st_size:,} bytes")

        print("\n🚀 Ready for LightRAG web interface upload!")
        print("=" * 70)

    def process(self) -> None:
        """Main processing workflow."""

        logger.info("🚀 Starting QA processing for LightRAG...")
        logger.info(f"Input: {self.input_file}")
        logger.info(f"Output: {self.output_file}")

        try:
            # Load and process QA data
            self.load_qa_data()

            # Format for LightRAG
            document = self.format_for_lightrag()

            # Save output
            self.save_document(document)

            # Print statistics
            self.print_statistics()

            logger.info("✅ QA processing completed successfully!")

        except Exception as e:
            logger.error(f"❌ Processing failed: {e}")
            raise


def main():
    """Main entry point."""

    print("🔄 QA Data Preparation for LightRAG")
    print("=" * 50)

    # Configuration
    input_file = "logs/qa_log.jsonl"
    output_file = "ready_for_lightrag.txt"

    # Check for command line arguments
    if len(sys.argv) >= 2:
        input_file = sys.argv[1]
    if len(sys.argv) >= 3:
        output_file = sys.argv[2]

    print(f"📥 Input: {input_file}")
    print(f"📤 Output: {output_file}")
    print()

    try:
        # Create and run processor
        processor = QAProcessor(input_file, output_file)
        processor.process()

        print("\n🎉 Success! Document ready for LightRAG upload.")

    except FileNotFoundError as e:
        print(f"\n❌ Error: {e}")
        print("💡 Make sure the QA log file exists and has been generated by the QA Logger.")
        sys.exit(1)

    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        logger.exception("Full error details:")
        sys.exit(1)


if __name__ == "__main__":
    main()