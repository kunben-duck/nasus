package com.autotest.platform.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

@Entity
@Table(name = "test_executions")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TestExecution {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "tenant_id")
    private Long tenantId;
    
    @Column(nullable = false, unique = true, length = 50)
    private String executionId;
    
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "test_case_id", nullable = false)
    private TestCase testCase;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "test_script_id")
    private TestScript testScript;

    @Column(name = "script_record_id", length = 40)
    private String scriptRecordId;

    @Column(name = "preview_mode")
    private Boolean previewMode;
    
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private ExecutionStatus status = ExecutionStatus.PENDING;
    
    @Enumerated(EnumType.STRING)
    private ExecutionResult result;
    
    @Column(columnDefinition = "TEXT")
    private String logs;
    
    @Column(columnDefinition = "TEXT")
    private String errorMessage;
    
    @Column(length = 255)
    private String videoPath;
    
    @Column(length = 255)
    private String reportPath;
    
    @Column
    private Long duration;  // milliseconds
    
    @Column(length = 100)
    private String executedBy;
    
    @Column(length = 100)
    private String browser;
    
    @Column(length = 50)
    private String environment;
    
    @OneToMany(mappedBy = "execution", cascade = CascadeType.ALL, fetch = FetchType.LAZY)
    @Builder.Default
    private List<ExecutionScreenshot> screenshots = new ArrayList<>();
    
    @OneToMany(mappedBy = "execution", cascade = CascadeType.ALL, fetch = FetchType.LAZY)
    @Builder.Default
    private List<ExecutionTimeline> timeline = new ArrayList<>();
    
    @CreationTimestamp
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;
    
    @UpdateTimestamp
    private LocalDateTime updatedAt;
    
    private LocalDateTime startedAt;
    
    private LocalDateTime completedAt;
    
    public enum ExecutionStatus {
        PENDING, QUEUED, RUNNING, PAUSED, COMPLETED, CANCELLED, FAILED, TIMEOUT
    }
    
    public enum ExecutionResult {
        PASS, FAIL, SKIP, ERROR, WARNING
    }
}
