package com.autotest.platform.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "test_scripts")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TestScript {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "tenant_id")
    private Long tenantId;
    
    @Column(nullable = false, length = 100)
    private String name;
    
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private ScriptType scriptType = ScriptType.PLAYWRIGHT;
    
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Language language = Language.JAVASCRIPT;
    
    @Column(columnDefinition = "TEXT")
    private String code;
    
    @Column(columnDefinition = "TEXT")
    private String config;
    
    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Status status = Status.DRAFT;
    
    @OneToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "test_case_id", nullable = false)
    private TestCase testCase;
    
    @Column(length = 50)
    private String version;
    
    @Column(length = 255)
    private String filePath;
    
    @CreationTimestamp
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;
    
    @UpdateTimestamp
    private LocalDateTime updatedAt;
    
    public enum ScriptType {
        PLAYWRIGHT, SELENIUM, CYPRESS, APPIUM, REST_ASSURED
    }
    
    public enum Language {
        JAVASCRIPT, TYPESCRIPT, PYTHON, JAVA, CSHARP
    }
    
    public enum Status {
        DRAFT, GENERATING, READY, TESTING, PRODUCTION, DEPRECATED
    }
}
