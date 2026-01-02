from sqlalchemy import Column, String, DateTime, CheckConstraint, ForeignKey, Integer, Numeric, BigInteger, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import declarative_base
import uuid

# Base declarative class
Base = declarative_base()

# Table model
class Account(Base):
    __tablename__ = "account"

    account_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), nullable=False, unique=True)
    email = Column(String(100), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    account_type = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="ACTIVE")

    __table_args__ = (
        CheckConstraint("account_type IN ('FREE', 'PAID', 'SYSADMIN')", name="check_account_type"),
    )


# Free Account model
class FreeAccount(Base):
    __tablename__ = "free_account"

    account_id = Column(UUID(as_uuid=True), ForeignKey("account.account_id", ondelete="CASCADE"), primary_key=True)
    storage_limit_gb = Column(Integer, nullable=False, default=2)


# Paid Account model
class PaidAccount(Base):
    __tablename__ = "paid_account"

    account_id = Column(UUID(as_uuid=True), ForeignKey("account.account_id", ondelete="CASCADE"), primary_key=True)
    storage_limit_gb = Column(Integer, nullable=False, default=30)
    monthly_cost = Column(Numeric(10, 2), nullable=False, default=10.00)
    start_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    renewal_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), nullable=False, default="ACTIVE")

    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'CANCELLED', 'EXPIRED')", name="check_paid_account_status"),
    )


# Folder model
class Folder(Base):
    __tablename__ = "folder"

    folder_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    account_id = Column(UUID(as_uuid=True), ForeignKey("account.account_id", ondelete="CASCADE"), nullable=False)
    parent_folder_id = Column(UUID(as_uuid=True), ForeignKey("folder.folder_id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# FileObject model (minimal model for table creation in tests)
class FileObject(Base):
    __tablename__ = "file_objects"

    file_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("account.account_id"), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    logical_path = Column(Text, nullable=False)
    folder_id = Column(UUID(as_uuid=True), ForeignKey("folder.folder_id", ondelete="SET NULL"), nullable=True)


# Password Reset Token model
class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    token_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("account.account_id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# Activity Log model
class ActivityLog(Base):
    __tablename__ = "activity_log"

    activity_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("account.account_id", ondelete="CASCADE"), nullable=False)
    action_type = Column(String(50), nullable=False)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(UUID(as_uuid=True), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    details = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# Erasure Profile model
class ErasureProfile(Base):
    __tablename__ = "erasure_profile"

    erasure_id = Column(String(50), primary_key=True)
    k = Column(Integer, nullable=False)
    m = Column(Integer, nullable=False)
    bytes = Column(Integer, nullable=False)
    notes = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("erasure_id IN ('LOW', 'MEDIUM', 'HIGH')", name="check_erasure_id"),
    )


# Account Erasure preference model
class AccountErasure(Base):
    __tablename__ = "account_erasure"

    account_id = Column(UUID(as_uuid=True), ForeignKey("account.account_id", ondelete="CASCADE"), primary_key=True)
    erasure_id = Column(String(50), ForeignKey("erasure_profile.erasure_id"), nullable=False)


# File Share model
class FileShare(Base):
    __tablename__ = "file_shares"

    share_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("file_objects.file_id", ondelete="CASCADE"), nullable=False)
    shared_by = Column(UUID(as_uuid=True), ForeignKey("account.account_id", ondelete="CASCADE"), nullable=False)
    shared_with = Column(UUID(as_uuid=True), ForeignKey("account.account_id", ondelete="CASCADE"), nullable=True)  # None for public links
    share_token = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=True)  # One-time password hash
    permissions = Column(String(20), nullable=False, default="VIEW")  # VIEW, DOWNLOAD
    expires_at = Column(DateTime(timezone=True), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)  # When password was used
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active = Column(String(10), nullable=False, default="ACTIVE")

    __table_args__ = (
        CheckConstraint("permissions IN ('VIEW', 'DOWNLOAD')", name="check_share_permissions"),
        CheckConstraint("is_active IN ('ACTIVE', 'EXPIRED', 'REVOKED')", name="check_share_status"),
    )


# Folder Share model
class FolderShare(Base):
    __tablename__ = "folder_shares"

    share_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    folder_id = Column(UUID(as_uuid=True), ForeignKey("folder.folder_id", ondelete="CASCADE"), nullable=False)
    shared_by = Column(UUID(as_uuid=True), ForeignKey("account.account_id", ondelete="CASCADE"), nullable=False)
    shared_with = Column(UUID(as_uuid=True), ForeignKey("account.account_id", ondelete="CASCADE"), nullable=True)  # None for public links
    share_token = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=True)  # One-time password hash
    permissions = Column(String(20), nullable=False, default="VIEW")  # VIEW, DOWNLOAD
    expires_at = Column(DateTime(timezone=True), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)  # When password was used
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active = Column(String(10), nullable=False, default="ACTIVE")

    __table_args__ = (
        CheckConstraint("permissions IN ('VIEW', 'DOWNLOAD')", name="check_folder_share_permissions"),
        CheckConstraint("is_active IN ('ACTIVE', 'EXPIRED', 'REVOKED')", name="check_folder_share_status"),
    )


# Share Access Log model
class ShareAccessLog(Base):
    __tablename__ = "share_access_log"

    access_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    share_id = Column(UUID(as_uuid=True), nullable=False)  # Can reference file_shares or folder_shares
    share_type = Column(String(10), nullable=False)  # FILE or FOLDER
    accessed_by = Column(UUID(as_uuid=True), ForeignKey("account.account_id"), nullable=True)  # None for anonymous access
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    action = Column(String(50), nullable=False)  # VIEW, DOWNLOAD, PASSWORD_ATTEMPT
    success = Column(String(10), nullable=False, default="SUCCESS")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("share_type IN ('FILE', 'FOLDER')", name="check_share_type"),
        CheckConstraint("action IN ('VIEW', 'DOWNLOAD', 'PASSWORD_ATTEMPT')", name="check_access_action"),
        CheckConstraint("success IN ('SUCCESS', 'FAILED')", name="check_access_success"),
    )


# Recycle Bin model
class RecycleBin(Base):
    __tablename__ = "recycle_bin"

    bin_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("account.account_id", ondelete="CASCADE"), nullable=False)
    resource_type = Column(String(10), nullable=False)  # FILE or FOLDER
    resource_id = Column(UUID(as_uuid=True), nullable=False)  # Original file_id or folder_id
    original_name = Column(String(255), nullable=False)
    original_path = Column(Text, nullable=True)  # Store full path for context
    original_size = Column(BigInteger, nullable=True)  # For files only
    deleted_by = Column(UUID(as_uuid=True), ForeignKey("account.account_id", ondelete="CASCADE"), nullable=False)
    deleted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)  # Set to deleted_at + 30 days
    deletion_reason = Column(String(100), nullable=True)  # USER_DELETE, ADMIN_DELETE, etc.
    bin_metadata = Column(JSONB, nullable=True)  # Additional context (renamed from metadata)
    is_recovered = Column(String(10), nullable=False, default="FALSE")  # FALSE, TRUE
    recovered_at = Column(DateTime(timezone=True), nullable=True)
    recovered_by = Column(UUID(as_uuid=True), ForeignKey("account.account_id"), nullable=True)

    __table_args__ = (
        CheckConstraint("resource_type IN ('FILE', 'FOLDER')", name="check_bin_resource_type"),
        CheckConstraint("is_recovered IN ('FALSE', 'TRUE')", name="check_bin_recovered"),
    )
