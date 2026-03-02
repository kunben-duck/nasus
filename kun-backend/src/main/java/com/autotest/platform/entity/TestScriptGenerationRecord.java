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
        name = "test_script_generation_records",
        indexes = {
                @Index(name = "idx_ts_gen_tenant_case_created", columnList = "tenant_id,test_case_id,created_at"),
                @Index(name = "idx_ts_gen_session_created", columnList = "session_id,created_at")
        }
)
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TestScriptGenerationRecord {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "record_id", nullable = false, unique = true, length = 40)
    private String recordId;

    @Column(name = "tenant_id", nullable = false)
    private Long tenantId;

    @Column(name = "session_id", nullable = false, length = 64)
    private String sessionId;

    @Column(nullable = false)
    private Integer version;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "test_case_id", nullable = false)
    private TestCase testCase;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "test_script_id")
    private TestScript testScript;

    @Enumerated(EnumType.STRING)
    @Column(name = "script_type", nullable = false, length = 32)
    private TestScript.ScriptType scriptType;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    private TestScript.Language language;

    @Column(name = "target_url", length = 512)
    private String targetUrl;

    @Column(columnDefinition = "TEXT")
    private String feedback;

    @Column(length = 255)
    private String summary;

    @Column(name = "dependencies_json", columnDefinition = "TEXT")
    private String dependenciesJson;

    @Column(name = "prompt_text", columnDefinition = "TEXT")
    private String promptText;

    @Column(name = "generated_code", columnDefinition = "TEXT", nullable = false)
    private String generatedCode;

    @Column(name = "model_provider", length = 32)
    private String modelProvider;

    @Column(name = "model_name", length = 128)
    private String modelName;

    @Column(name = "requested_by", length = 100)
    private String requestedBy;

    @Column(name = "adopted")
    private Boolean adopted;

    @Column(name = "adopted_at")
    private LocalDateTime adoptedAt;

    @Column(name = "adopted_by", length = 100)
    private String adoptedBy;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;
}
