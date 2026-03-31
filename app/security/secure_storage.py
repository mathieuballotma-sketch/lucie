from __future__ import annotations

import os
import sqlite3
import struct
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..utils.logger import logger
from ..utils.crypto import SERVICE_NAME

# Magic header and version for encrypted files
MAGIC_HEADER = b"LUCIE_EC"  # 8 bytes
VERSION = 0x01
KEYRING_SERVICE = "com.lucie.secure-storage"
KEYRING_USERNAME = "master_key"
BLOCK_SIZE = 1048576  # 1 MB for chunked encryption/decryption
NONCE_SIZE = 12  # 12 bytes for GCM
GCM_TAG_SIZE = 16  # GCM authentication tag
SALT_SIZE = 32  # 32 bytes for HKDF salt
MASTER_KEY_SIZE = 32  # 32 bytes for AES-256


class SecureStorage:
    """
    Advanced encryption layer for Lucie providing:
    - AES-256-GCM encryption at rest for all sensitive files
    - Key derivation via HKDF from master secret in Keychain/fallback storage
    - Per-file salt for unique key derivation
    - Block-based encryption for large files (FAISS indexes)
    - Transparent read/write operations
    - SQLite database encryption support
    - Migration detection and in-place file encryption

    File Header Format:
    [MAGIC 8 bytes "LUCIE_EC"][VERSION 1 byte][SALT 32 bytes][blocks...]

    Block Format:
    [NONCE 12 bytes][CIPHERTEXT + GCM TAG]
    """

    def __init__(self, data_dir: str = "data") -> None:
        """
        Initialize SecureStorage and get or create master key from Keychain.

        Args:
            data_dir: Base directory for encrypted data storage (default: "data")
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.master_key = self._get_or_create_master_key()
        logger.info(f"🔐 SecureStorage initialized (data_dir: {self.data_dir})")

    def _get_or_create_master_key(self) -> bytes:
        """
        Retrieve or create a 32-byte master key from Keychain (macOS)
        or fallback in-memory storage (Linux/other platforms).

        Returns:
            bytes: 32-byte master key for HKDF derivation
        """
        if KEYRING_AVAILABLE:
            try:
                stored_key_b64 = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
                if stored_key_b64:
                    import base64
                    key = base64.b64decode(stored_key_b64)
                    if len(key) == MASTER_KEY_SIZE:
                        logger.info("✓ Master key loaded from Keychain")
                        return key
            except Exception as e:
                logger.warning(f"⚠️ Keyring access failed: {e}, falling back to in-memory storage")

        # Fallback: in-memory or file-based storage
        fallback_key_file = self.data_dir / ".master_key"
        if fallback_key_file.exists():
            try:
                import base64
                key = base64.b64decode(fallback_key_file.read_bytes())
                if len(key) == MASTER_KEY_SIZE:
                    logger.info("✓ Master key loaded from fallback storage")
                    return key
            except Exception as e:
                logger.warning(f"⚠️ Fallback key load failed: {e}")

        # Generate new master key
        new_master_key = os.urandom(MASTER_KEY_SIZE)

        if KEYRING_AVAILABLE:
            try:
                import base64
                keyring.set_password(
                    KEYRING_SERVICE,
                    KEYRING_USERNAME,
                    base64.b64encode(new_master_key).decode()
                )
                logger.info("✓ New master key stored in Keychain")
                return new_master_key
            except Exception as e:
                logger.warning(f"⚠️ Could not store key in Keychain: {e}")

        # Fallback: store in secured file
        try:
            import base64
            fallback_key_file.write_bytes(base64.b64encode(new_master_key))
            fallback_key_file.chmod(0o600)
            logger.info(f"✓ New master key stored in fallback location: {fallback_key_file}")
        except Exception as e:
            logger.error(f"❌ Could not store master key: {e}")
            raise

        return new_master_key

    def _derive_key(self, salt: bytes, context: str = "file") -> bytes:
        """
        Derive a file-specific key from master key using HKDF-SHA256.

        Args:
            salt: 32-byte salt for this file (should be unique per file)
            context: Context string for HKDF (default: "file")

        Returns:
            bytes: 32-byte derived key suitable for AES-256
        """
        if len(salt) != SALT_SIZE:
            raise ValueError(f"Salt must be {SALT_SIZE} bytes, got {len(salt)}")

        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=context.encode(),
            backend=default_backend()
        )
        return hkdf.derive(self.master_key)

    def write_encrypted(self, filepath: str, data: bytes) -> None:
        """
        Encrypt and write data to a file with AES-256-GCM.

        File format: MAGIC(8) VERSION(1) SALT(32) [NONCE(12) CIPHERTEXT+TAG]...

        Args:
            filepath: Path to output file
            data: Raw bytes to encrypt

        Raises:
            IOError: If file write fails
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Generate unique salt for this file
        salt = os.urandom(SALT_SIZE)
        derived_key = self._derive_key(salt, context=filepath.name)

        # Encrypt in single block if small
        if len(data) <= BLOCK_SIZE:
            nonce = os.urandom(NONCE_SIZE)
            cipher = AESGCM(derived_key)
            ciphertext = cipher.encrypt(nonce, data, None)

            with open(filepath, "wb") as f:
                f.write(MAGIC_HEADER)
                f.write(bytes([VERSION]))
                f.write(salt)
                f.write(nonce)
                f.write(ciphertext)

            logger.debug(f"✓ Encrypted file: {filepath}")
        else:
            # Use block-based encryption for large data
            self.write_encrypted_blocks(filepath, data, block_size=BLOCK_SIZE)

    def read_decrypted(self, filepath: str) -> bytes:
        """
        Read and decrypt a file encrypted with write_encrypted().

        Args:
            filepath: Path to encrypted file

        Returns:
            bytes: Decrypted raw data

        Raises:
            ValueError: If magic header or version mismatch
            cryptography.exceptions.InvalidTag: If decryption fails
        """
        filepath = Path(filepath)

        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        with open(filepath, "rb") as f:
            # Read header
            magic = f.read(8)
            if magic != MAGIC_HEADER:
                raise ValueError(f"Invalid magic header: {magic!r}")

            version = f.read(1)[0]
            if version != VERSION:
                raise ValueError(f"Unsupported version: {version}")

            salt = f.read(SALT_SIZE)
            if len(salt) != SALT_SIZE:
                raise ValueError(f"Incomplete salt read")

            derived_key = self._derive_key(salt, context=filepath.name)

            # Read all encrypted blocks
            decrypted_data = b""
            while True:
                nonce = f.read(NONCE_SIZE)
                if not nonce:
                    break

                if len(nonce) != NONCE_SIZE:
                    raise ValueError("Incomplete nonce read")

                # Read until end of file for this block
                ciphertext_and_tag = f.read()
                if not ciphertext_and_tag:
                    break

                cipher = AESGCM(derived_key)
                try:
                    plaintext = cipher.decrypt(nonce, ciphertext_and_tag, None)
                    decrypted_data += plaintext
                except Exception as e:
                    logger.error(f"❌ Decryption failed for {filepath}: {e}")
                    raise

        logger.debug(f"✓ Decrypted file: {filepath}")
        return decrypted_data

    def write_encrypted_blocks(
        self,
        filepath: str,
        data: bytes,
        block_size: int = BLOCK_SIZE
    ) -> None:
        """
        Encrypt and write large data in blocks (for FAISS indexes, large DBs).

        Each block is encrypted independently with its own nonce.
        File format: MAGIC(8) VERSION(1) SALT(32) NUM_BLOCKS(4) [BLOCK_LEN(4) NONCE(12) CIPHERTEXT+TAG]...

        Args:
            filepath: Path to output file
            data: Raw bytes to encrypt
            block_size: Size of each block in bytes (default: 1MB)

        Raises:
            IOError: If file write fails
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Generate unique salt for this file
        salt = os.urandom(SALT_SIZE)
        derived_key = self._derive_key(salt, context=filepath.name)

        with open(filepath, "wb") as f:
            # Write header
            f.write(MAGIC_HEADER)
            f.write(bytes([VERSION]))
            f.write(salt)

            # Encrypt and write blocks
            cipher = AESGCM(derived_key)
            num_blocks = (len(data) + block_size - 1) // block_size

            # Write number of blocks
            f.write(struct.pack(">I", num_blocks))

            for i in range(num_blocks):
                start = i * block_size
                end = min(start + block_size, len(data))
                block = data[start:end]

                nonce = os.urandom(NONCE_SIZE)
                ciphertext = cipher.encrypt(nonce, block, None)

                # Write block length, nonce, and ciphertext
                f.write(struct.pack(">I", len(block)))
                f.write(nonce)
                f.write(ciphertext)

                if (i + 1) % 10 == 0:
                    logger.debug(f"  Encrypted block {i + 1}/{num_blocks}")

        logger.info(f"✓ Encrypted {len(data)} bytes in {num_blocks} blocks: {filepath}")

    def read_decrypted_blocks(self, filepath: str) -> bytes:
        """
        Read and decrypt a file encrypted with write_encrypted_blocks().

        Args:
            filepath: Path to encrypted file with blocks

        Returns:
            bytes: Complete decrypted data

        Raises:
            ValueError: If magic header or version mismatch
            cryptography.exceptions.InvalidTag: If decryption fails
        """
        filepath = Path(filepath)

        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        with open(filepath, "rb") as f:
            # Read header
            magic = f.read(8)
            if magic != MAGIC_HEADER:
                raise ValueError(f"Invalid magic header: {magic!r}")

            version = f.read(1)[0]
            if version != VERSION:
                raise ValueError(f"Unsupported version: {version}")

            salt = f.read(SALT_SIZE)
            if len(salt) != SALT_SIZE:
                raise ValueError("Incomplete salt read")

            derived_key = self._derive_key(salt, context=filepath.name)
            cipher = AESGCM(derived_key)

            # Read number of blocks
            num_blocks_bytes = f.read(4)
            if len(num_blocks_bytes) < 4:
                raise ValueError("Could not read block count")

            num_blocks = struct.unpack(">I", num_blocks_bytes)[0]
            logger.debug(f"Reading {num_blocks} blocks from {filepath.name}")

            # Read and decrypt blocks
            decrypted_data = b""

            for block_num in range(num_blocks):
                # Read block length
                block_len_bytes = f.read(4)
                if len(block_len_bytes) < 4:
                    raise ValueError(f"Could not read block {block_num} length")

                block_len = struct.unpack(">I", block_len_bytes)[0]

                # Read nonce
                nonce = f.read(NONCE_SIZE)
                if len(nonce) != NONCE_SIZE:
                    raise ValueError(f"Incomplete nonce for block {block_num}")

                # Read ciphertext (block + GCM tag)
                ciphertext_and_tag = f.read(block_len + GCM_TAG_SIZE)
                if len(ciphertext_and_tag) < block_len + GCM_TAG_SIZE:
                    raise ValueError(f"Incomplete ciphertext for block {block_num}")

                try:
                    plaintext = cipher.decrypt(nonce, ciphertext_and_tag, None)
                    decrypted_data += plaintext

                    if (block_num + 1) % 10 == 0:
                        logger.debug(f"  Decrypted block {block_num + 1}/{num_blocks}")

                except Exception as e:
                    logger.error(f"❌ Block decryption failed at block {block_num}: {e}")
                    raise

        logger.info(f"✓ Decrypted {len(decrypted_data)} bytes from {num_blocks} blocks: {filepath}")
        return decrypted_data

    def is_encrypted(self, filepath: str) -> bool:
        """
        Check if a file is encrypted (has valid LUCIE_EC magic header).

        Args:
            filepath: Path to check

        Returns:
            bool: True if file has valid encryption header, False otherwise
        """
        filepath = Path(filepath)

        if not filepath.exists():
            return False

        try:
            with open(filepath, "rb") as f:
                magic = f.read(8)
                return magic == MAGIC_HEADER
        except Exception:
            return False

    @contextmanager
    def encrypted_sqlite_connect(
        self,
        db_path: str,
        timeout: float = 30.0
    ) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for transparent SQLite database encryption.

        Decrypts the database to a temporary file, yields connection,
        and re-encrypts on close. Falls back to direct connection if not encrypted.

        Usage:
            with secure_storage.encrypted_sqlite_connect("data/app.db") as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM table")

        Args:
            db_path: Path to encrypted or plain SQLite database
            timeout: Connection timeout in seconds

        Yields:
            sqlite3.Connection: Active database connection

        Raises:
            sqlite3.Error: If database operations fail
        """
        db_path = Path(db_path)
        is_encrypted = self.is_encrypted(db_path)

        # Decrypt to temporary file if needed
        if is_encrypted:
            logger.debug(f"Decrypting SQLite database: {db_path}")
            db_plaintext = self.read_decrypted(db_path)

            # Create temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                tmp_path = tmp.name
                tmp.write(db_plaintext)

            logger.debug(f"Database decrypted to temp: {tmp_path}")
        else:
            tmp_path = str(db_path)
            logger.debug(f"Using unencrypted database: {db_path}")

        try:
            # Open connection to decrypted/plain database
            conn = sqlite3.connect(tmp_path, timeout=timeout)
            logger.debug(f"✓ SQLite connection opened: {tmp_path}")

            yield conn

            # Commit any pending transactions
            conn.commit()
            conn.close()
            logger.debug("✓ SQLite connection closed and committed")

            # Always encrypt on close (new or existing)
            source_path = tmp_path if is_encrypted else str(db_path)
            with open(source_path, "rb") as f:
                db_plaintext = f.read()

            self.write_encrypted(str(db_path), db_plaintext)
            logger.info(f"✓ Database encrypted: {db_path}")

        finally:
            # Clean up temp file
            if is_encrypted and Path(tmp_path).exists():
                try:
                    Path(tmp_path).unlink()
                    logger.debug(f"Cleaned up temp database: {tmp_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not delete temp file {tmp_path}: {e}")

    def migrate_file(self, filepath: str) -> bool:
        """
        Encrypt an unencrypted file in-place.

        Reads the plaintext file, encrypts it, and replaces the original.
        Creates a backup with .plaintext extension.

        Args:
            filepath: Path to file to encrypt

        Returns:
            bool: True if migration successful, False if already encrypted

        Raises:
            FileNotFoundError: If file does not exist
            IOError: If read/write fails
        """
        filepath = Path(filepath)

        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        if self.is_encrypted(filepath):
            logger.info(f"⚠️ File already encrypted: {filepath}")
            return False

        try:
            # Read plaintext
            plaintext = filepath.read_bytes()

            # Create backup
            backup_path = filepath.with_suffix(filepath.suffix + ".plaintext")
            backup_path.write_bytes(plaintext)
            backup_path.chmod(0o600)
            logger.info(f"  Backup created: {backup_path}")

            # Encrypt and write over original
            self.write_encrypted(str(filepath), plaintext)
            logger.info(f"✓ File migrated to encrypted: {filepath}")

            return True

        except Exception as e:
            logger.error(f"❌ Migration failed for {filepath}: {e}")
            raise

    def migrate_all(
        self,
        directory: str,
        patterns: Optional[list[str]] = None
    ) -> dict:
        """
        Scan directory and migrate all unencrypted files matching patterns.

        By default migrates: *.db, *.sqlite, *.json, *.faiss

        Args:
            directory: Directory to scan recursively
            patterns: List of glob patterns to match (default: common data files)

        Returns:
            dict: {
                'migrated': [list of successfully migrated files],
                'skipped': [list of already encrypted files],
                'failed': [list of failed files with error messages]
            }
        """
        directory = Path(directory)

        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")

        if patterns is None:
            patterns = ["*.db", "*.sqlite", "*.json", "*.faiss"]

        results = {"migrated": [], "skipped": [], "failed": []}

        logger.info(f"Scanning directory for migration: {directory}")
        logger.info(f"  Patterns: {patterns}")

        # Find matching files
        files_to_migrate = []
        for pattern in patterns:
            files_to_migrate.extend(directory.rglob(pattern))

        # Remove duplicates
        files_to_migrate = list(set(files_to_migrate))

        logger.info(f"Found {len(files_to_migrate)} potential files to migrate")

        for filepath in sorted(files_to_migrate):
            try:
                if self.is_encrypted(filepath):
                    results["skipped"].append(str(filepath))
                    logger.debug(f"  Skipped (already encrypted): {filepath.name}")
                else:
                    self.migrate_file(filepath)
                    results["migrated"].append(str(filepath))

            except Exception as e:
                results["failed"].append((str(filepath), str(e)))
                logger.error(f"  Failed: {filepath.name} - {e}")

        logger.info(f"Migration complete:")
        logger.info(f"  Migrated: {len(results['migrated'])}")
        logger.info(f"  Skipped: {len(results['skipped'])}")
        logger.info(f"  Failed: {len(results['failed'])}")

        return results
