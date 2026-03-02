package com.autotest.platform.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "validation_points")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class ValidationPoint {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "tenant_id")
    private Long tenantId;
    
    @Column(nullable = false, length = 500)
    private String description;
    
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Priority priority = Priority.MEDIUM;
    
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Status status = Status.PENDING;
    
    @Column(columnDefinition = "TEXT")
    private String expectedResult;
    
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_story_id", nullable = false)
    private UserStory userStory;
    
    @OneToOne(mappedBy = "validationPoint", cascade = CascadeType.ALL, fetch = FetchType.LAZY)
    private TestCase testCase;
    
    @CreationTimestamp
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;
    
    @UpdateTimestamp
    private LocalDateTime updatedAt;
    
    public enum Priority {
        LOW, MEDIUM, HIGH, CRITICAL
    }
    
    public enum Status {
        PENDING, COVERED, FAILED, PASSED
    }
}
