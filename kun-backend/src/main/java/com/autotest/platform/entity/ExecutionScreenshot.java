package com.autotest.platform.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "execution_screenshots")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class ExecutionScreenshot {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "execution_id", nullable = false)
    private TestExecution execution;
    
    @Column(nullable = false, columnDefinition = "TEXT")
    private String filePath;
    
    @Column(length = 100)
    private String stepName;
    
    @Column
    private Integer stepNumber;
    
    @Column(length = 500)
    private String description;
    
    @Enumerated(EnumType.STRING)
    private ScreenshotType type = ScreenshotType.NORMAL;
    
    @CreationTimestamp
    @Column(nullable = false, updatable = false)
    private LocalDateTime capturedAt;
    
    public enum ScreenshotType {
        NORMAL, ERROR, SUCCESS, WARNING
    }
}
