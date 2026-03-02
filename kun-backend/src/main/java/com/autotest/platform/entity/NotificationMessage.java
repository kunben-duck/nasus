package com.autotest.platform.entity;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(
        name = "notifications",
        indexes = {
                @Index(name = "idx_notifications_user_tenant_created", columnList = "user_id,tenant_id,created_at"),
                @Index(name = "idx_notifications_user_tenant_read", columnList = "user_id,tenant_id,is_read")
        }
)
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class NotificationMessage {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "tenant_id", nullable = false)
    private Long tenantId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 64)
    private NotificationType type;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 24)
    @Builder.Default
    private NotificationLevel level = NotificationLevel.INFO;

    @Column(nullable = false, length = 200)
    private String title;

    @Column(columnDefinition = "TEXT")
    private String content;

    @Column(name = "related_resource_type", length = 64)
    private String relatedResourceType;

    @Column(name = "related_resource_id", length = 128)
    private String relatedResourceId;

    @Column(name = "is_read", nullable = false)
    @Builder.Default
    private Boolean read = Boolean.FALSE;

    private LocalDateTime readAt;

    @CreationTimestamp
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;

    public enum NotificationType {
        US_ANALYSIS_SUCCEEDED,
        US_ANALYSIS_FAILED,
        CASE_GENERATION_SUCCEEDED,
        CASE_GENERATION_FAILED,
        SCRIPT_GENERATION_SUCCEEDED,
        SCRIPT_GENERATION_FAILED
    }

    public enum NotificationLevel {
        INFO,
        SUCCESS,
        WARNING,
        ERROR
    }
}
