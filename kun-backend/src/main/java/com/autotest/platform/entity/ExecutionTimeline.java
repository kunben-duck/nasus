package com.autotest.platform.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "execution_timeline")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class ExecutionTimeline {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "execution_id", nullable = false)
    private TestExecution execution;
    
    @Column(nullable = false)
    private Integer stepOrder;
    
    @Column(nullable = false, length = 100)
    private String stepName;
    
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private StepStatus status;
    
    @Column
    private Long duration;  // milliseconds
    
    @Column(columnDefinition = "TEXT")
    private String details;
    
    @Column(columnDefinition = "TEXT")
    private String screenshotPath;
    
    @CreationTimestamp
    @Column(nullable = false, updatable = false)
    private LocalDateTime timestamp;
    
    public enum StepStatus {
        STARTED, IN_PROGRESS, COMPLETED, FAILED, SKIPPED
    }
}
