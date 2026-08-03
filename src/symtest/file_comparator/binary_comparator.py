#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file binary_comparator.py
@brief Binary file comparator implementation with efficient byte-level comparison
@author Xiaotong Wang
@date 2025
"""

import difflib
import hashlib
from .base_comparator import BaseComparator
from .result import Difference

class BinaryComparator(BaseComparator):
    """
    @brief Comparator for binary files with efficient byte-level comparison
    @details This class implements binary file comparison with support for:
             - Byte-level difference detection
             - Similarity index calculation using LCS
             - Parallel processing for large files
             - File hash calculation
    """
    
    def __init__(self, encoding="utf-8", chunk_size=8192, verbose=False, similarity=False, num_threads=4, **kwargs):
        """
        @brief Initialize the binary comparator
        @param encoding str: File encoding (not used for binary files)
        @param chunk_size int: Size of chunks for reading large files
        @param verbose bool: Enable verbose logging
        @param similarity bool: Enable similarity index calculation
        @param num_threads int: Number of threads for parallel processing
        @param **kwargs: Additional parameters (ignored)
        """
        super().__init__(encoding=encoding, chunk_size=chunk_size, verbose=verbose, **kwargs)
        self.similarity = similarity
        self.num_threads = num_threads

    def read_content(self, file_path, start_line=0, end_line=None, start_column=0, end_column=None):
        """
        @brief Read binary content with specified range
        @param file_path Path: Path to the binary file to read
        @param start_line int: Starting byte offset (interpreted as bytes for binary files)
        @param end_line int: Ending byte offset (interpreted as bytes for binary files)
        @param start_column int: Ignored for binary files
        @param end_column int: Ignored for binary files
        @return bytes: Binary content within the specified range
        @throws ValueError: If byte offsets are invalid
        @throws FileNotFoundError: If file doesn't exist
        @throws IOError: If there are other file reading errors
        """
        try:
            self.logger.debug(f"Reading binary file: {file_path}")
            
            # For binary files, interpret start_line as byte offset
            start_offset = start_line
            end_offset = end_line
            
            with open(file_path, 'rb') as f:
                if start_offset > 0:
                    f.seek(start_offset)
                
                if end_offset is not None:
                    if end_offset <= start_offset:
                        raise ValueError("End offset must be greater than start offset")
                    bytes_to_read = end_offset - start_offset
                    content = f.read(bytes_to_read)
                else:
                    content = f.read()
                    
            return content
                
        except FileNotFoundError:
            raise ValueError(f"File not found: {file_path}")
        except IOError as e:
            raise ValueError(f"Error reading file {file_path}: {str(e)}")
    
    def compare_content(self, content1, content2):
        """
        @brief Compare binary content efficiently
        @param content1 bytes: First binary content to compare
        @param content2 bytes: Second binary content to compare
        @return tuple: (bool, list, bool) - (identical, differences, truncated)
        @details Performs efficient byte-level comparison of binary content.
                 Reports differences with hex context and limits the number
                 of differences to avoid overwhelming output.
        """
        self.logger.debug(f"Comparing binary content")
        
        if len(content1) != len(content2):
            differences = [Difference(
                position="file size",
                expected=f"{len(content1)} bytes",
                actual=f"{len(content2)} bytes",
                diff_type="size"
            )]
            identical = False
            truncated = False
        elif content1 == content2:
            differences = []
            identical = True
            truncated = False
        else:
            identical = False
            differences = []
            offset = 0
            max_differences = 10  # Limit number of differences reported
            truncated = False
        
            for i in range(0, len(content1), self.chunk_size):
                chunk1 = content1[i:i+self.chunk_size]
                chunk2 = content2[i:i+self.chunk_size]
                
                if chunk1 != chunk2:
                    # Find the exact byte position where the difference starts
                    for j in range(len(chunk1)):
                        if j >= len(chunk2) or chunk1[j] != chunk2[j]:
                            diff_pos = i + j
                            # Show a few bytes before and after the difference for context
                            context_size = 8
                            start_ctx = max(0, diff_pos - context_size)
                            end_ctx = min(len(content1), diff_pos + context_size)
                            
                            # Create hex representations of the differing sections
                            expected_bytes = content1[start_ctx:end_ctx]
                            actual_bytes = content2[start_ctx:min(len(content2), end_ctx)]
                            
                            expected_hex = ' '.join(f"{b:02x}" for b in expected_bytes)
                            actual_hex = ' '.join(f"{b:02x}" for b in actual_bytes)
                            
                            differences.append(Difference(
                                position=f"byte {diff_pos}",
                                expected=expected_hex,
                                actual=actual_hex,
                                diff_type="content"
                            ))
                            break
                            
                    if len(differences) >= max_differences:
                        truncated = True
                        break
        
        return identical, differences, truncated

    def _compute_similarity(self, a: bytes, b: bytes) -> float:
        """
        @brief Compute similarity ratio between two binary sequences.
        @param a bytes: First binary sequence
        @param b bytes: Second binary sequence
        @return float: Similarity ratio in [0.0, 1.0]
        @details Uses difflib.SequenceMatcher for accurate comparison on small/medium
                 files, and hash-based chunk comparison for large files to avoid
                 O(n*m) complexity that would be infeasible on large binaries.
        """
        if not a and not b:
            return 1.0

        total_bytes = len(a) + len(b)
        if total_bytes == 0:
            return 1.0

        # difflib.SequenceMatcher uses a heuristic matching algorithm that works well
        # for files under ~1 MB. Beyond that, fall back to chunk-hash approximation.
        if total_bytes <= 1024 * 1024:
            matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
            return matcher.ratio()

        return self._hash_chunk_similarity(a, b)

    def _hash_chunk_similarity(self, a: bytes, b: bytes) -> float:
        """
        @brief Approximate similarity via chunk-level hash matching for large files.
        @param a bytes: First binary sequence
        @param b bytes: Second binary sequence
        @return float: Approximate similarity ratio in [0.0, 1.0]
        @details Splits both inputs into fixed-size chunks (4 KB), hashes each chunk,
                 and computes Jaccard similarity on the chunk hash sets. This avoids
                 O(n*m) DP while giving a reasonable estimate of binary similarity.
        """
        chunk_size = 4096

        hashes_a = set()
        for i in range(0, len(a), chunk_size):
            hashes_a.add(hash(a[i:i + chunk_size]))

        hashes_b = set()
        for i in range(0, len(b), chunk_size):
            hashes_b.add(hash(b[i:i + chunk_size]))

        if not hashes_a and not hashes_b:
            return 1.0

        intersection = len(hashes_a & hashes_b)
        union = len(hashes_a | hashes_b)

        if union == 0:
            return 1.0

        return intersection / union

    def compare_files(self, file1, file2, start_line=0, end_line=None, start_column=0, end_column=None):
        """
        @brief Compare two binary files with optional similarity calculation using chunk-based streaming
        @param file1 Path: Path to the first binary file
        @param file2 Path: Path to the second binary file
        @param start_line int: Starting byte offset
        @param end_line int: Ending byte offset
        @param start_column int: Ignored for binary files
        @param end_column int: Ignored for binary files
        @return ComparisonResult: Result object containing comparison details
        @details This method implements chunk-based streaming comparison to avoid loading
                 entire files into memory, making it suitable for large files with O(1) memory usage.
        """
        from pathlib import Path
        from .result import ComparisonResult
        result = ComparisonResult(
            file1=str(file1),
            file2=str(file2),
            start_line=start_line,
            end_line=end_line,
            start_column=start_column,
            end_column=end_column
        )
        try:
            self.logger.info(f"Comparing files: {file1} and {file2}")
            file1_path = Path(file1)
            file2_path = Path(file2)
            result.file1_size = file1_path.stat().st_size
            result.file2_size = file2_path.stat().st_size
            
            # Quick size check: if file sizes differ and similarity is not requested, 
            # we can return early without streaming
            if result.file1_size != result.file2_size and not self.similarity:
                # Adjust sizes based on offset if specified
                adjusted_size1 = result.file1_size - start_line
                adjusted_size2 = result.file2_size - start_line
                if end_line is not None:
                    adjusted_size1 = min(adjusted_size1, end_line - start_line)
                    adjusted_size2 = min(adjusted_size2, end_line - start_line)
                
                if adjusted_size1 != adjusted_size2:
                    result.identical = False
                    result.differences.append(Difference(
                        position="file size",
                        expected=f"{result.file1_size} bytes",
                        actual=f"{result.file2_size} bytes",
                        diff_type="size"
                    ))
                    return result
            
            # If similarity calculation is needed, we still need to read full content
            # but for regular comparison, use chunk-based streaming
            if self.similarity:
                # Similarity calculation requires full content for SequenceMatcher
                # or chunk-hash comparison
                self.logger.debug("Reading full content for similarity calculation")
                content1 = self.read_content(file1, start_line, end_line, start_column, end_column)
                content2 = self.read_content(file2, start_line, end_line, start_column, end_column)
                identical, differences, truncated = self.compare_content(content1, content2)
                result.similarity = self._compute_similarity(content1, content2)
            else:
                # Chunk-based streaming comparison for O(1) memory usage
                self.logger.debug("Using chunk-based streaming comparison")
                identical, differences, truncated = self._compare_files_streaming(
                    file1_path, file2_path, start_line, end_line
                )
            
            result.identical = identical
            result.differences = differences
            result.truncated = truncated
            return result
        except Exception as e:
            self.logger.error(f"Error during comparison: {str(e)}")
            result.error = str(e)
            result.identical = False
            return result
    
    def _compare_files_streaming(self, file1_path, file2_path, start_offset=0, end_offset=None):
        """
        @brief Compare two binary files using chunk-based streaming
        @param file1_path Path: Path to the first binary file
        @param file2_path Path: Path to the second binary file
        @param start_offset int: Starting byte offset
        @param end_offset int: Ending byte offset (None for end of file)
        @return tuple: (bool, list, bool) - (identical, differences, truncated)
        @details This method compares files chunk by chunk without loading entire files
                 into memory, achieving O(1) memory complexity.
        """
        differences = []
        max_differences = 10  # Limit number of differences reported
        truncated = False
        
        try:
            with open(file1_path, 'rb') as f1, open(file2_path, 'rb') as f2:
                # Seek to start offset if specified
                if start_offset > 0:
                    f1.seek(start_offset)
                    f2.seek(start_offset)
                
                # Calculate bytes to read if end_offset is specified
                bytes_to_read = None
                if end_offset is not None:
                    if end_offset <= start_offset:
                        raise ValueError("End offset must be greater than start offset")
                    bytes_to_read = end_offset - start_offset
                
                chunk_size = self.chunk_size
                current_offset = start_offset
                bytes_read_total = 0
                
                while True:
                    # Determine how many bytes to read in this chunk
                    if bytes_to_read is not None:
                        remaining = bytes_to_read - bytes_read_total
                        if remaining <= 0:
                            break
                        read_size = min(chunk_size, remaining)
                    else:
                        read_size = chunk_size
                    
                    # Read chunks from both files
                    chunk1 = f1.read(read_size)
                    chunk2 = f2.read(read_size)
                    
                    # If both files are exhausted, we're done
                    if not chunk1 and not chunk2:
                        break
                    
                    # If one file ends before the other, that's a difference
                    if len(chunk1) != len(chunk2):
                        differences.append(Difference(
                            position=f"byte {current_offset}",
                            expected=f"{len(chunk1)} bytes in chunk",
                            actual=f"{len(chunk2)} bytes in chunk",
                            diff_type="content"
                        ))
                        break
                    
                    # Compare chunks byte by byte
                    if chunk1 != chunk2:
                        # Find the exact byte position where the difference starts
                        for i in range(len(chunk1)):
                            if chunk1[i] != chunk2[i]:
                                abs_pos = current_offset + i
                                
                                # Show a few bytes before and after the difference for context
                                context_size = 8
                                context_start = max(0, i - context_size)
                                context_end = min(len(chunk1), i + context_size)
                                
                                # Get context bytes (may need to read previous chunk)
                                context1 = chunk1[context_start:context_end]
                                context2 = chunk2[context_start:context_end]
                                
                                expected_hex = ' '.join(f"{b:02x}" for b in context1)
                                actual_hex = ' '.join(f"{b:02x}" for b in context2)
                                
                                differences.append(Difference(
                                    position=f"byte {abs_pos}",
                                    expected=expected_hex,
                                    actual=actual_hex,
                                    diff_type="content"
                                ))
                                
                                # Stop after finding first difference in chunk
                                # or if we've reached max differences
                                if len(differences) >= max_differences:
                                    truncated = True
                                    return False, differences, truncated
                                break
                    
                    current_offset += len(chunk1)
                    bytes_read_total += len(chunk1)
                    
                    # If we didn't read a full chunk, we've reached EOF
                    if len(chunk1) < read_size:
                        break
                
                identical = len(differences) == 0
                return identical, differences, truncated
                
        except FileNotFoundError as e:
            raise ValueError(f"File not found: {e}")
        except IOError as e:
            raise ValueError(f"Error reading file: {str(e)}")

    def get_file_hash(self, file_path, chunk_size=8192):
        """
        @brief Calculate SHA-256 hash of a file efficiently
        @param file_path Path: Path to the file to hash
        @param chunk_size int: Size of chunks for reading large files
        @return str: Hexadecimal representation of the file's SHA-256 hash
        """
        h = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(chunk_size), b''):
                h.update(chunk)
        return h.hexdigest()